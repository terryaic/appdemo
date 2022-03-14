import omni.kit.test
import omni.kit.app
import carb.settings
import carb.tokens
from .utils import do_screen_capture, getStageDefaultPrimPath, LogErrorChecker
import carb
import os
import random
import tempfile
from pathlib import Path
import carb.tokens

import omni.kit.commands
import omni.usd
import omni.kit.undo
from pxr import Gf, UsdGeom


# TODO: Test assets to be loaded...do we definitely have access to this? We should use
# new CI kit server, but it seems to not be available

KITCHEN_SINK_PATH = "omniverse://kit.nucleus.ov-ci.nvidia.com/Projects/create_startup_tests/Collected_Kitchen_set_front_on/Kitchen_set_front_on.usd"
ASTRONAUT_PATH = "omniverse://kit.nucleus.ov-ci.nvidia.com//NVIDIA/Samples/Astronaut/Astronaut.usd"

# Constants for BasicTests class
CURRENT_PATH = Path(__file__).parent.joinpath("data").absolute().resolve()
FILE_PATH_ROOT = str(CURRENT_PATH.joinpath("material_root.usda")).replace("\\", "/")
FILE_PATH_MODIFIED = str(CURRENT_PATH.joinpath("material_root_modified.usda")).replace("\\", "/")


class SceneLoadTests(omni.kit.test.AsyncTestCase):
    """
    #TODO add shader compile warm step?
    """

    fail_on_log_error = False  # Switch to true will cause tests to fail

    threshold: float = 0.03

  

    async def load_and_compare(self, name: str, asset_path: str, num_assets: int) -> float:
      
        omni.kit.pipapi.install("dssim_py", extra_args=["--extra-index-url", "https://pypi.perflab.nvidia.com/simple/"])
        import dssim_py  # from https://gitlab-master.nvidia.com/ovat/libraries/dssim-py

        golden_file = Path(__file__).parent / "data" / ("golden_" + name + ".png")
        result_file = self.output_dir / ("out_" + name + ".png")
        diff_file = self.output_dir / ("diff_" + name + ".png")
        elapsed_time = await do_screen_capture(asset_path, str(result_file), self.syncloads, num_assets)
        print(name, "ELAPSED TIME for ", elapsed_time)


        ssim = dssim_py.compare(str(golden_file), str(result_file), diff_output=str(diff_file))
        print(f"##teamcity[publishArtifacts '{result_file} => results']")
        print(f"##teamcity[publishArtifacts '{golden_file} => golden']")
        print(f"##teamcity[publishArtifacts '{diff_file} => diff']")
        print(name, "SSIM value", float(ssim), str(golden_file), str(result_file))
        return ssim

    def setUp(self):
        # TODO: need to not move this out
        os.environ["OMNI_USER"] = "omniverse"
        os.environ["OMNI_PASS"] = "omniverse"

        settings_interface = carb.settings.get_settings()
        self.syncloads = settings_interface.get("/rtx/materialDb/syncLoads") and settings_interface.get(
            "/omni.kit.plugin/syncUsdLoads"
        )
        self.output_dir = Path(tempfile.mkdtemp())

    #@unittest.skip("Fails")
    async def test_load_kitchen_set(self):
        name = "pixar_kitchen_set"
        ssim_val = await self.load_and_compare(name, KITCHEN_SINK_PATH, 0)
        self.assertTrue(ssim_val < self.threshold, "difference in images %s above threshold" % (ssim_val))

    #@unittest.skip("Fails")
    async def test_load_astronaut(self):
        name = "astronaut"
        ssim_val = await self.load_and_compare(name, ASTRONAUT_PATH, 1)
        self.assertTrue(ssim_val < self.threshold, "difference in images %s above threshold" % (ssim_val))

    async def test_public_release_configuration(self):
        settings = carb.settings.get_settings()
        app_version = settings.get("/app/version")

        # This test covers a moment in time when we switch version to RC.
        # Following test cases must be satisfied.
        is_rc = "-rc." in app_version

        # Make sure we set build to external when going into RC release mode
        external = settings.get("/privacy/externalBuild") or False
        self.assertEqual(external, is_rc, "check failed: is this an RC build? %s Is /privacy/externalBuild set to true? %s"%(is_rc, external))

        # Make sure we remove tracy from public release
        manager = omni.kit.app.get_app().get_extension_manager()
        ext_names = {e["name"] for e in manager.get_extensions()}
        self.assertEqual("omni.kit.profiler.tracy" in ext_names, not is_rc, "looks like omni.kit.profiler.tracy was not removed from public build")


class BasicTests(omni.kit.test.AsyncTestCase):
    """
    Basic sanity checks for Create. UPDATE: bulk usd tests have been moved into their own extension.
    """

    async def setUp(self):
        await omni.usd.get_context().new_stage_async()
        omni.usd.get_context().get_layers().set_layer_edit_mode(omni.usd.LayerEditMode.NORMAL)

    async def tearDown(self):
        await omni.usd.get_context().close_stage_async()

    async def test_open_modify_save_usd(self):
        """
        Open a usd, make changes, save to new file. Verify changes are present in new file.
        """

        usd_context = omni.usd.get_context()
        stage_opens = usd_context.open_stage(FILE_PATH_ROOT)
        self.assertTrue(stage_opens, "Stage failed to open")

        # Verify that things in the file are where they are expected to be
        stage = usd_context.get_stage()
        default_prim_path = getStageDefaultPrimPath(stage)
        prim = stage.GetPrimAtPath(default_prim_path.AppendChild("Cube"))
        xformable = UsdGeom.Xformable(prim)

        # Make changes and save to a new file
        translate_mtx = Gf.Matrix4d()
        rand_x = random.randrange(100, 300)
        rand_y = random.randrange(100, 300)
        rand_z = random.randrange(100, 300)
        translate_mtx.SetTranslate(Gf.Vec3d(rand_x, rand_y, rand_z))

        omni.kit.commands.execute(
            "TransformPrim",
            path=default_prim_path.AppendChild("Cube"),
            new_transform_matrix=translate_mtx
        )

        modified_cube_position = xformable.GetLocalTransformation()  # used for later assert

        # Export changes to new file
        rootlayer = stage.GetRootLayer()
        rootlayer.Export(FILE_PATH_MODIFIED)
        usd_context.close_stage()

        # Open export and verify changes
        usd_context.open_stage(FILE_PATH_MODIFIED)
        modified_stage = usd_context.get_stage()
        self.assertTrue(modified_stage, "Stage changes were not saved to new usda")

        modified_default_prim_path = getStageDefaultPrimPath(modified_stage)
        modified_prim = modified_stage.GetPrimAtPath(modified_default_prim_path.AppendChild("Cube"))
        modified_xformable = UsdGeom.Xformable(modified_prim)
        modified_transform_matrix = modified_xformable.GetLocalTransformation()
        self.assertTrue(
            Gf.IsClose(modified_cube_position, modified_transform_matrix, 0.00001),
            "Changes to usda were not saved"
        )

        # Set material_root_modified.usda back to initial state
        reset_mtx = Gf.Matrix4d()
        reset_mtx.SetTranslate(Gf.Vec3d(1.0))
        omni.kit.commands.execute(
            "TransformPrim",
            path=modified_default_prim_path.AppendChild("Cube"),
            new_transform_matrix=reset_mtx
        )
        usd_context.save_stage()

    async def test_load_extensions(self):
        """
        Test loading featured extensions in the script
        """

        manager = omni.kit.app.get_app().get_extension_manager()
        settings = carb.settings.get_settings()
        featured_exts = set(settings.get("/exts/omni.kit.window.extensions/featuredExts"))

        EXCLUDES = ["omni.kit.tools.surface_instancer", "omni.kit.console", "omni.kit.quicksearch.commands"]

        for ext in manager.get_extensions():
            ext_id = ext["id"]
            # Skip core extensions
            info = manager.get_extension_dict(ext_id)
            if manager.is_extension_enabled(ext_id):
                continue
            if info["package"].get("feature", False) or ext["name"] in featured_exts:
                if ext["name"] in EXCLUDES:
                    continue
                print(f"test_load_extensions: Enabling {ext_id}")
                checker = LogErrorChecker()
                manager.set_extension_enabled_immediate(ext_id, True)
                for _ in range(5):
                    await omni.kit.app.get_app().next_update_async()
                self.assertTrue(manager.is_extension_enabled(ext_id), f"Extension failed to load: {ext_id}")
                error_count = checker.get_error_count()
                self.assertEqual(error_count, 0, f"Extension produced {error_count} errors when starting: {ext_id}")
