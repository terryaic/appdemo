import asyncio
import carb
import omni.kit.app
import os
import time
from typing import List
import urllib

from pxr import Sdf

original_persistent_settings = {}
settings_interface = None
event_map = {}
for _val in dir(omni.usd.StageEventType):
    if _val.isupper():
        event_map[int(getattr(omni.usd.StageEventType, _val))] = _val


def set_persistent_setting(name, value, type):
    global original_persistent_settings, settings_interface

    _orig = settings_interface.get(name)  # noqa
    original_persistent_settings[name] = {"value": _orig, "type": type}

    _set_settings_value(name, value, type)


def restore_persistent_settings():
    for name, _dict in original_persistent_settings.items():
        _set_settings_value(name, _dict["value"], _dict["type"])


def _set_settings_value(name, value, type):
    global settings_interface
    settings_interface.set(name, value)


async def stage_event() -> int:
    """Calls `kit.stage_event` with logging"""
    result = await omni.usd.get_context().next_stage_event_async()
    event, _ = result
    event = int(event)
    carb.log_info(f"*** create_startup_tests: stage_event() -> ({event_map[event]}, {_})")
    return event


async def capture_next_frame(app, capture_file_path: str):
    """
    capture that works with old (editor-based) capture and new Kit 2.0 approach also
    Not all Create's seem to have the new API available (e.g "omni.create.kit")
    """

    _renderer = None
    _viewport_interface = None

    try:
        import omni.renderer_capture
        import omni.kit.viewport
    except ImportError as ie:
        carb.log_error(f"*** screenshot: capture_next_frame: can't load {ie}")

    _renderer = omni.renderer_capture.acquire_renderer_capture_interface()
    _viewport_interface = omni.kit.viewport.acquire_viewport_interface()
    viewport_ldr_rp = _viewport_interface.get_viewport_window(None).get_drawable_ldr_resource()

    # TODO: Probably need to put a cap on this so doesnt hang forever
    # Wait until the viewport has valid resources
    while viewport_ldr_rp == None:
        await app.next_update_async()
        viewport_ldr_rp = _viewport_interface.get_viewport_window(None).get_drawable_ldr_resource()

    _renderer.capture_next_frame_rp_resource(capture_file_path, viewport_ldr_rp)
    await app.next_update_async()
    _renderer.wait_async_capture()
    print("written", capture_file_path)


def omni_url_parser(url: str):
    res = urllib.parse.urlparse(url)
    username = os.getenv("OMNI_USER", default="test")
    password = os.getenv("OMNI_PASS", default=username)
    return res.netloc, username, password, res.path


async def load_stage(stage_path: str, syncloads: bool, num_assets_loaded: int = 2):

    start = time.time()
    success, explanation = await omni.usd.get_context().open_stage_async(stage_path)
    carb.log_info(f"*** create_startup_tests: Initial stage load success: {success}")
    if not success:
        raise RuntimeError(explanation)

    # we'll try to track all the ASSETS_LOADED events to figure out when the MDLs
    # are complete
    assets_loaded_count = 0
    required_assets_loaded = 1
    if not syncloads:
        required_assets_loaded = int(num_assets_loaded)

    if required_assets_loaded == 0:
        load_time = time.time() - start
        carb.log_info("*** create_startup_tests: Not waiting for ASSETS LOADED at all, stage load complete.")
        return load_time

    carb.log_info(f"*** create_startup_tests: Waiting for {required_assets_loaded} ASSETS LOADED event(s)")
    while True:
        event = await stage_event()
        # TODO: compare to actual enum value when Kit fixes its return types
        if event == int(omni.usd.StageEventType.ASSETS_LOADED):
            assets_loaded_count += 1
            carb.log_info(f"*** create_startup_tests: Received ASSETS_LOADED #{assets_loaded_count}")
            # The user can specify how many assets_loaded to wait for in async mode
            if assets_loaded_count < required_assets_loaded:
                continue
            carb.log_info(f"*** create_startup_tests: Met threshold of {required_assets_loaded}, all assets loaded")
            break
        # error that something went wrong
        elif event == int(omni.usd.StageEventType.OPEN_FAILED):
            raise RuntimeError("Received OPEN_FAILED")
        elif event == int(omni.usd.StageEventType.ASSETS_LOAD_ABORTED):
            raise RuntimeError("Received ASSETS_LOAD_ABORTED")
        elif event == int(omni.usd.StageEventType.CLOSING):
            raise SystemExit("Received CLOSING")
        elif event == int(omni.usd.StageEventType.CLOSED):
            raise SystemExit("Received CLOSED")

    load_time = time.time() - start
    return load_time


def getStageDefaultPrimPath(stage):
    """
    Helper function used for getting default prim path for any given stage.
    """
    if stage.HasDefaultPrim():
        return stage.GetDefaultPrim().GetPath()
    else:
        return Sdf.Path.absoluteRootPath


async def load_featured_extensions():
    """
    Load and enable all Kit extension with featured tag.

    Returns:
        List of all extensions that were enabled
    """

    manager = omni.kit.app.get_app().get_extension_manager()
    settings = carb.settings.get_settings()
    featured_exts = settings.get("/exts/omni.kit.window.extensions/featuredExts")
    EXCLUDES = ["omni.kit.tools.surface_instancer", "omni.kit.console", "omni.kit.quicksearch.commands"]
    loaded_extensions = []

    for ext in manager.get_extensions():
        ext_id = ext["id"]
        # Skip core extensions
        info = manager.get_extension_dict(ext_id)
        if manager.is_extension_enabled(ext_id):
            continue
        if info["package"].get("feature", False) or ext["name"] in featured_exts:
            if ext["name"] in EXCLUDES:
                continue
            loaded_extensions.append(ext_id)
            manager.set_extension_enabled_immediate(ext_id, True)
            for _ in range(5):
                await omni.kit.app.get_app().next_update_async()

    print(f"Extensions under test: {loaded_extensions}")


async def do_screen_capture(stage_path, output_file_path, syncloads, num_assets):
    '''
    once we move to Kit 103, see https://nvidia-omniverse.atlassian.net/browse/OM-37242
    '''
    _timeout = 500
    wait_after_load = 10
    carb.log_info(f"*** create_startup_tests: Loading {stage_path}")
    try:
        load_time = await asyncio.wait_for(load_stage(stage_path, syncloads, num_assets), _timeout)
    except RuntimeError as e:
        carb.log_error(f"*** create_startup_tests: Stage load failure: {e}")
        # reset what we persisted
        restore_persistent_settings()
        return
    except SystemExit as e:
        carb.log_error(f"*** create_startup_tests: Stage load aborted: {e}")
        restore_persistent_settings()
        return
    except asyncio.TimeoutError:
        carb.log_error(f"*** create_startup_tests: Timed out when waiting {_timeout} for the stage to load")
        restore_persistent_settings()
        return
    carb.log_info(f"*** create_startup_tests: scene loaded in {load_time}s")

    settings_interface = carb.settings.get_settings()
    settings_interface.set_float("/rtx/post/tonemap/op", 6)

    # sleep some user-defined seconds just to let the scene settle
    carb.log_info(f"*** create_startup_tests: waiting {wait_after_load}s for the scene to settle")
    await asyncio.sleep(wait_after_load)

    app = omni.kit.app.get_app()
    await capture_next_frame(app, output_file_path)

    # need to wait a second or two for the screenshot to get written
    await asyncio.sleep(5)
    carb.log_info(f"*** create_startup_tests: screenshot captured to: {output_file_path}")
    return load_time


class LogErrorChecker:
    """Automatically subscribes to logging events and monitors if error were produced during the test."""

    def __init__(self):
        # Setup this test case to fail if any error is produced
        self._error_count = 0

        def on_log_event(e):
            if e.payload["level"] >= carb.logging.LEVEL_ERROR:
                self._error_count = self._error_count + 1

        self._log_stream = omni.kit.app.get_app().get_log_event_stream()
        self._log_sub = self._log_stream.create_subscription_to_pop(on_log_event, name="test log event")

    def shutdown(self):
        self._log_stream = None
        self._log_sub = None

    def get_error_count(self):
        self._log_stream.pump()
        return self._error_count
