# Copyright (c) 2018-2020, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.
#

import asyncio
import sys
import os
import omni.ext
import omni.ui as ui
import carb.settings
import omni.kit.commands
import carb.imgui as _imgui
import carb.tokens
import omni.kit.menu.utils
import omni.kit.app
import omni.kit.ui
import omni.kit.stage_templates as stage_templates
from omni.kit.window.title import get_main_window_title
from omni.kit.quicklayout import QuickLayout

import carb.input

from pathlib import Path

DATA_PATH = Path(__file__).parent.parent.parent.parent.parent


async def _load_layout(layout_file: str):
    # few frames delay to avoid the conflict with the layout of omni.kit.mainwindow
    for i in range(3):
        await omni.kit.app.get_app().next_update_async()

    QuickLayout.load_file(layout_file)



class CreateSetupExtension(omni.ext.IExt):
    """Create Final Configuration"""

    def on_startup(self, ext_id):
        """ setup the window layout, menu, final configuration of the extensions etc """
        self._settings = carb.settings.get_settings()

        # this is a work around as some Extensions don't properly setup their default setting in time
        self._set_defaults()

        carb.log_info(f"settings:{self._settings}")
        # adjust couple of viewport settings
        self._settings.set("/app/viewport/grid/enabled", True)
        self._settings.set("/app/viewport/outline/enabled", False)
        self._settings.set("/app/viewport/boundingBoxes/enabled", False)
        self._settings.set("/app/viewport/displayOptions", 3574)

        # Adjust the Window Title to show the Create Version
        window_title = get_main_window_title()

        app_version = self._settings.get("/app/version")
        if not app_version:
            app_version = open(carb.tokens.get_tokens_interface().resolve("${app}/../VERSION")).read()

        if app_version:
            if "+" in app_version:
                app_version, _ = app_version.split("+")

            # for RC version we remove some details
            PRODUCTION = True
            if PRODUCTION:
                if "-" in app_version:
                    app_version, _ = app_version.split("-")
                window_title.set_app_version(app_version)
            else:
                window_title.set_app_version(app_version)

        # setup some imgui Style overide
        imgui = _imgui.acquire_imgui()
        imgui.push_style_color(_imgui.StyleColor.ScrollbarGrab, carb.Float4(0.4, 0.4, 0.4, 1))
        imgui.push_style_color(_imgui.StyleColor.ScrollbarGrabHovered, carb.Float4(0.6, 0.6, 0.6, 1))
        imgui.push_style_color(_imgui.StyleColor.ScrollbarGrabActive, carb.Float4(0.8, 0.8, 0.8, 1))

        imgui.push_style_var_float(_imgui.StyleVar.DockSplitterSize, 2)

        layout_file = f"{DATA_PATH}/layouts/default.json"
        self.__setup_window_task = asyncio.ensure_future(_load_layout(layout_file))

        self.__setup_property_window = asyncio.ensure_future(self.__property_window())

        self.__menu_update()

        self.__await_new_scene = asyncio.ensure_future(self.__new_stage())

        # final Layout alingment ...
        render_settings = ui.Workspace.get_window("RTX Settings")
        if render_settings:
            render_settings.dock_order = 2

        startup_time = omni.kit.app.get_app_interface().get_time_since_start_s()
        self._settings.set("/crashreporter/data/startup_time", f"{startup_time}")

    def _set_defaults(self):
        """ this is trying to setup some defaults for extensions to avoid warning """
        self._settings.set_default("/persistent/app/omniverse/bookmarks", {})
        self._settings.set_default("/persistent/app/stage/timeCodeRange", [0, 100])

        self._settings.set_default("/persistent/audio/context/closeAudioPlayerOnStop", False)

        self._settings.set_default("/persistent/app/primCreation/PrimCreationWithDefaultXformOps", True)
        self._settings.set_default("/persistent/app/primCreation/DefaultXformOpType", "Scale, Rotate, Translate")
        self._settings.set_default("/persistent/app/primCreation/DefaultRotationOrder", "ZYX")
        self._settings.set_default("/persistent/app/primCreation/DefaultXformOpPrecision", "Double")

        # omni.kit.property.tagging
        self._settings.set_default("/persistent/exts/omni.kit.property.tagging/showAdvancedTagView", False)
        self._settings.set_default("/persistent/exts/omni.kit.property.tagging/showHiddenTags", False)
        self._settings.set_default("/persistent/exts/omni.kit.property.tagging/modifyHiddenTags", False)

    @classmethod
    async def __new_stage(cls):
        # disable hang detector while app is starting
        hang_detector_disable_key = "/app/hangDetector/disableReasons/startingApp"
        settings = carb.settings.get_settings()
        settings.set(hang_detector_disable_key, "1")

        window = ui.Window("STARTING RTX", height=100, flags=ui.WINDOW_FLAGS_NO_TITLE_BAR)
        with window.frame:
            with ui.VStack(height=80):
                ui.Spacer()
                ui.Label("... RTX Loading ....", alignment=ui.Alignment.CENTER, style={"font_size": 18})
                ui.Spacer()

        # 10 frame delay to allow Layout
        for i in range(10):
            await omni.kit.app.get_app().next_update_async()

        stage_templates.new_stage(template=None)

        # for i in range(5):
        #     await omni.kit.app.get_app().next_update_async()

        window.visible = False
        window = None
        settings.destroy_item(hang_detector_disable_key)

    def _launch_app(self, app_id, console=True, custom_args=None):
        """launch an other Kit app with the same settings"""
        import sys
        import subprocess
        import platform

        app_path = carb.tokens.get_tokens_interface().resolve("${app}")
        kit_file_path = os.path.join(app_path, app_id)

        launch_args = [sys.argv[0]]
        launch_args += [kit_file_path]
        if custom_args:
            launch_args.extend(custom_args)

        # Pass all exts folders
        exts_folders = self._settings.get("/app/exts/folders")
        if exts_folders:
            for folder in exts_folders:
                launch_args.extend(["--ext-folder", folder])

        kwargs = {"close_fds": False}
        if platform.system().lower() == "windows":
            if console:
                kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        subprocess.Popen(launch_args, **kwargs)

    def _show_ui_docs(self):
        """ show the omniverse ui documentation as an external Application """
        self._launch_app("omni.app.uidoc.kit")

    def _show_launcher(self):
        """ show the omniverse ui documentation as an external Application """
        self._launch_app("omni.create.launcher.kit", console=False, custom_args={"--/app/auto_launch=false"})

    async def __property_window(self):
        await omni.kit.app.get_app().next_update_async()
        import omni.kit.window.property as property_window_ext

        property_window = property_window_ext.get_window()
        property_window.set_scheme_delegate_layout(
            "Create Layout", ["path_prim", "material_prim", "xformable_prim", "shade_prim", "camera_prim"]
        )

    def __menu_update(self):
        # Remove some Menu Items
        editor_menu = omni.kit.ui.get_editor_menu()
        editor_menu.remove_item("Window/New Viewport Window")

        editor_menu.set_priority("Rendering/Render Settings", -100)
        editor_menu.set_priority("Rendering/Movie Capture", 100)

        # set omnu.ui Help Menu
        self._ui_doc_menu_path = "Help/Omni UI Docs"
        self._ui_doc_menu_item = editor_menu.add_item(self._ui_doc_menu_path, lambda *_: self._show_ui_docs())
        editor_menu.set_priority(self._ui_doc_menu_path, -10)

        self._layout_menu_items = []
        self._current_layout_priority = 20

        def add_layout_menu_entry(name, path, key):
            menu_path = f"Window/Layout/{name}"
            menu = editor_menu.add_item(menu_path, None, self._current_layout_priority)
            self._current_layout_priority = self._current_layout_priority + 1
            menu_action = omni.kit.menu.utils.add_action_to_menu(
                menu_path,
                lambda *_: asyncio.ensure_future(_load_layout(f"{DATA_PATH}/layouts/{path}.json")),
                name,
                (carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL, key),
            )

            self._layout_menu_items.append((menu, menu_action))

        add_layout_menu_entry("Reset Layout", "default", carb.input.KeyboardInput.KEY_1)
        add_layout_menu_entry("Viewport Only", "viewportOnly", carb.input.KeyboardInput.KEY_2)
        add_layout_menu_entry("Stage Viewer", "stageViewer", carb.input.KeyboardInput.KEY_3)
        #  add_layout_menu_entry("Sequencer", "sequencer", carb.input.KeyboardInput.KEY_4)
        add_layout_menu_entry("Paint", "paint", carb.input.KeyboardInput.KEY_4)
        #  add_layout_menu_entry("Camera Animation", "cameraAnimation", carb.input.KeyboardInput.KEY_6)

    def on_shutdown(self):
        self._layout_menu_items = None
        self._ui_doc_menu_item = None
        self._launcher_menu = None
        self._reset_menu = None
