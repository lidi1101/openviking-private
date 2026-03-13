import builtins
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pybind11
from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

CMAKE_PATH = os.environ.get("CMAKE") or shutil.which("cmake") or "cmake"
C_COMPILER_PATH = os.environ.get("CC") or shutil.which("gcc")
CXX_COMPILER_PATH = os.environ.get("CXX") or shutil.which("g++")
AR_PATH = os.environ.get("AR") or shutil.which("ar")
ENGINE_SOURCE_DIR = "src/"


def _safe_print(*args, **kwargs):
    """Print build logs safely on Windows GBK consoles."""
    try:
        builtins.print(*args, **kwargs)
    except UnicodeEncodeError:
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        text = sep.join(str(arg) for arg in args)
        encoding = getattr(sys.stdout, "encoding", None) or "gbk"
        safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding)
        builtins.print(safe_text, end=end)


print = _safe_print





class OpenVikingBuildExt(build_ext):
    """Build OpenViking runtime artifacts and Python native extensions."""

    def run(self):
        self.build_agfs_artifacts()
        self.build_ov_cli_artifact()
        self.cmake_executable = CMAKE_PATH

        for ext in self.extensions:
            self.build_extension(ext)

    def _copy_artifact(self, src, dst):
        """Copy a build artifact into the package tree and preserve executability."""
        print(f"Copying artifact from {src} to {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        if sys.platform != "win32":
            os.chmod(str(dst), 0o755)

    def _copy_artifacts_to_build_lib(self, target_binary=None, target_lib=None):
        """Copy built artifacts into build_lib so wheel packaging can include them."""
        if self.build_lib:
            build_pkg_dir = Path(self.build_lib) / "openviking"
            if target_binary and target_binary.exists():
                self._copy_artifact(target_binary, build_pkg_dir / "bin" / target_binary.name)
            if target_lib and target_lib.exists():
                self._copy_artifact(target_lib, build_pkg_dir / "lib" / target_lib.name)

    def _decode_subprocess_output(self, content):
        if not content:
            return ""
        return content.decode("utf-8", errors="replace")

    def _run_subprocess(self, args, cwd, env, error_prefix):
        try:
            result = subprocess.run(
                args,
                cwd=str(cwd),
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            cmd_name = args[0]
            raise RuntimeError(
                f"{error_prefix}: required command '{cmd_name}' was not found on PATH"
            ) from exc
        except subprocess.CalledProcessError as exc:
            error_msg = f"{error_prefix}: Command '{args}' returned non-zero exit status {exc.returncode}."
            if exc.stdout:
                error_msg += f"\nBuild stdout: {self._decode_subprocess_output(exc.stdout)}"
            if exc.stderr:
                error_msg += f"\nBuild stderr: {self._decode_subprocess_output(exc.stderr)}"
            raise RuntimeError(error_msg) from exc

        if result.stdout:
            print(f"Build stdout: {self._decode_subprocess_output(result.stdout)}")
        if result.stderr:
            print(f"Build stderr: {self._decode_subprocess_output(result.stderr)}")
        return result

    def _resolve_windows_cmake_generator_args(self):
        if not C_COMPILER_PATH or not CXX_COMPILER_PATH:
            raise RuntimeError(
                "Windows source builds require MinGW-w64 gcc/g++ on PATH because the "
                "native extension and AGFS binding library do not currently support MSVC."
            )

        mingw_make = shutil.which("mingw32-make")
        if mingw_make:
            return [
                "-G",
                "MinGW Makefiles",
                f"-DCMAKE_MAKE_PROGRAM={mingw_make}",
            ]

        ninja = shutil.which("ninja")
        if ninja:
            return ["-G", "Ninja"]

        raise RuntimeError(
            "Windows source builds require either 'mingw32-make' or 'ninja' on PATH "
            "alongside MinGW-w64 gcc/g++."
        )

    def _should_skip_windows_ov_build(self):
        if sys.platform != "win32":
            return False, ""

        if os.environ.get("OPENVIKING_SKIP_OV_BUILD") == "1":
            return (
                True,
                "OPENVIKING_SKIP_OV_BUILD=1 is set. Skipping ov CLI build on Windows.",
            )

        cargo_path = shutil.which("cargo")
        if not cargo_path:
            return False, ""

        if shutil.which("link.exe"):
            return False, ""

        try:
            result = subprocess.run(
                ["rustc", "-vV"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception:
            return False, ""

        rustc_info = self._decode_subprocess_output(result.stdout)
        host_line = next(
            (line.strip() for line in rustc_info.splitlines() if line.startswith("host: ")),
            "",
        )
        if host_line.endswith("windows-msvc"):
            return (
                True,
                "Detected Rust MSVC toolchain on Windows without 'link.exe'. "
                "Skipping ov CLI build because it requires Visual C++ Build Tools or a GNU Rust target.",
            )

        return False, ""

    def _configure_windows_cargo_env(self, env):
        if sys.platform != "win32":
            return env

        configured_env = env.copy()

        if not configured_env.get("CARGO_BUILD_TARGET"):
            if C_COMPILER_PATH and CXX_COMPILER_PATH:
                configured_env["CARGO_BUILD_TARGET"] = "x86_64-pc-windows-gnu"

        if configured_env.get("CARGO_BUILD_TARGET") == "x86_64-pc-windows-gnu":
            configured_env.setdefault("CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER", C_COMPILER_PATH or "gcc")
            if AR_PATH:
                configured_env.setdefault("CARGO_TARGET_X86_64_PC_WINDOWS_GNU_AR", AR_PATH)

        return configured_env

    def _require_artifact(self, artifact_path, artifact_name, stage_name):
        """Abort the build immediately when a required artifact is missing."""
        if artifact_path.exists():
            return
        raise RuntimeError(
            f"{stage_name} did not produce required {artifact_name} at {artifact_path}"
        )

    def _run_stage_with_artifact_checks(
        self, stage_name, build_fn, required_artifacts, on_success=None
    ):
        """Run a build stage and always validate its required outputs on normal return."""
        build_fn()
        for artifact_path, artifact_name in required_artifacts:
            self._require_artifact(artifact_path, artifact_name, stage_name)
        if on_success:
            on_success()

    def _resolve_cargo_target_dir(self, cargo_project_dir, env):
        """Resolve the Cargo target directory for workspace and overridden builds."""
        configured_target_dir = env.get("CARGO_TARGET_DIR")
        if configured_target_dir:
            return Path(configured_target_dir).resolve()

        try:
            result = subprocess.run(
                ["cargo", "metadata", "--format-version", "1", "--no-deps"],
                cwd=str(cargo_project_dir),
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            metadata = json.loads(result.stdout.decode("utf-8"))
            target_directory = metadata.get("target_directory")
            if target_directory:
                return Path(target_directory).resolve()
        except Exception as exc:
            print(f"[Warning] Failed to resolve Cargo target directory via metadata: {exc}")

        return cargo_project_dir.parents[1] / "target"

    def build_agfs_artifacts(self):
        """Build or reuse the AGFS server binary and binding library."""
        binary_name = "agfs-server.exe" if sys.platform == "win32" else "agfs-server"
        if sys.platform == "win32":
            lib_name = "libagfsbinding.dll"
        elif sys.platform == "darwin":
            lib_name = "libagfsbinding.dylib"
        else:
            lib_name = "libagfsbinding.so"

        agfs_server_dir = Path("third_party/agfs/agfs-server").resolve()
        agfs_bin_dir = Path("openviking/bin").resolve()
        agfs_lib_dir = Path("openviking/lib").resolve()
        agfs_target_binary = agfs_bin_dir / binary_name
        agfs_target_lib = agfs_lib_dir / lib_name

        self._run_stage_with_artifact_checks(
            "AGFS build",
            lambda: self._build_agfs_artifacts_impl(
                agfs_server_dir,
                binary_name,
                lib_name,
                agfs_target_binary,
                agfs_target_lib,
            ),
            [
                (agfs_target_binary, binary_name),
                (agfs_target_lib, lib_name),
            ],
            on_success=lambda: self._copy_artifacts_to_build_lib(
                agfs_target_binary, agfs_target_lib
            ),
        )

    def _build_agfs_artifacts_impl(
        self, agfs_server_dir, binary_name, lib_name, agfs_target_binary, agfs_target_lib
    ):
        """Implement AGFS artifact building without final artifact checks."""

        prebuilt_dir = os.environ.get("OV_PREBUILT_BIN_DIR")
        if prebuilt_dir:
            prebuilt_path = Path(prebuilt_dir).resolve()
            print(f"Checking for pre-built AGFS artifacts in {prebuilt_path}...")
            src_bin = prebuilt_path / binary_name
            src_lib = prebuilt_path / lib_name

            if src_bin.exists():
                self._copy_artifact(src_bin, agfs_target_binary)
            if src_lib.exists():
                self._copy_artifact(src_lib, agfs_target_lib)

            if agfs_target_binary.exists() and agfs_target_lib.exists():
                print(f"[OK] Used pre-built AGFS artifacts from {prebuilt_dir}")
                return

        if os.environ.get("OV_SKIP_AGFS_BUILD") == "1":
            if agfs_target_binary.exists() and agfs_target_lib.exists():
                print("[OK] Skipping AGFS build, using existing artifacts")
                return
            print("[Warning] OV_SKIP_AGFS_BUILD=1 but artifacts are missing. Will try to build.")

        if agfs_server_dir.exists() and shutil.which("go"):
            print("Building AGFS artifacts from source...")

            try:
                print(f"Building AGFS server: {binary_name}")
                env = os.environ.copy()
                if "GOOS" in env or "GOARCH" in env:
                    print(f"Cross-compiling with GOOS={env.get('GOOS')} GOARCH={env.get('GOARCH')}")

                build_args = (
                    ["go", "build", "-o", f"build/{binary_name}", "cmd/server/main.go"]
                    if sys.platform == "win32"
                    else ["make", "build"]
                )

                self._run_subprocess(
                    build_args,
                    cwd=str(agfs_server_dir),
                    env=env,
                    error_prefix="Failed to build AGFS server from source",
                )

                agfs_built_binary = agfs_server_dir / "build" / binary_name
                self._require_artifact(agfs_built_binary, binary_name, "AGFS server build")
                self._copy_artifact(agfs_built_binary, agfs_target_binary)
                print("[OK] AGFS server built successfully from source")
            except Exception as exc:
                error_msg = str(exc)
                print(f"[Error] {error_msg}")
                raise RuntimeError(error_msg)

            try:
                print(f"Building AGFS binding library: {lib_name}")
                env = os.environ.copy()
                env["CGO_ENABLED"] = "1"

                if sys.platform == "win32":
                    build_args = [
                        "go",
                        "build",
                        "-buildmode=c-shared",
                        "-o",
                        f"build/{lib_name}",
                        "cmd/pybinding/main.go",
                    ]
                else:
                    build_args = ["make", "build-lib"]

                self._run_subprocess(
                    build_args,
                    cwd=str(agfs_server_dir),
                    env=env,
                    error_prefix="Failed to build AGFS binding library",
                )

                agfs_built_lib = agfs_server_dir / "build" / lib_name
                self._require_artifact(agfs_built_lib, lib_name, "AGFS binding build")
                self._copy_artifact(agfs_built_lib, agfs_target_lib)
                print("[OK] AGFS binding library built successfully")
            except Exception as exc:
                error_msg = str(exc)
                print(f"[Error] {error_msg}")
                raise RuntimeError(error_msg)
        else:
            if agfs_target_binary.exists() and agfs_target_lib.exists():
                print("[Info] AGFS artifacts already exist locally. Skipping source build.")
            elif not agfs_server_dir.exists():
                print(f"[Warning] AGFS source directory not found at {agfs_server_dir}")
            else:
                print("[Warning] Go compiler not found. Cannot build AGFS from source.")

    def build_ov_cli_artifact(self):
        """Build or reuse the ov Rust CLI binary."""
        binary_name = "ov.exe" if sys.platform == "win32" else "ov"
        ov_cli_dir = Path("crates/ov_cli").resolve()
        ov_target_binary = Path("openviking/bin").resolve() / binary_name
        built_or_found = self._build_ov_cli_artifact_impl(
            ov_cli_dir, binary_name, ov_target_binary
        )
        if built_or_found:
            self._require_artifact(ov_target_binary, binary_name, "ov CLI build")
            self._copy_artifacts_to_build_lib(ov_target_binary, None)
        else:
            print(
                "[Warning] Skipping ov CLI packaging because no prebuilt binary was found "
                "and Cargo is unavailable. The 'openviking-server' entry point will still work, "
                "but the 'ov'/'openviking' CLI wrappers will require a separately installed ov binary."
            )

    def _build_ov_cli_artifact_impl(self, ov_cli_dir, binary_name, ov_target_binary):
        """Implement ov CLI building without final artifact checks."""

        prebuilt_dir = os.environ.get("OV_PREBUILT_BIN_DIR")
        if prebuilt_dir:
            src_bin = Path(prebuilt_dir).resolve() / binary_name
            if src_bin.exists():
                self._copy_artifact(src_bin, ov_target_binary)
                return True

        if os.environ.get("OV_SKIP_OV_BUILD") == "1" or os.environ.get("OPENVIKING_SKIP_OV_BUILD") == "1":
            if ov_target_binary.exists():
                print("[OK] Skipping ov CLI build, using existing binary")
                return True
            print(
                "[Warning] OV_SKIP_OV_BUILD=1/OPENVIKING_SKIP_OV_BUILD=1 and ov CLI binary is missing. "
                "Skipping build."
            )
            return False

        should_skip, skip_reason = self._should_skip_windows_ov_build()
        if should_skip:
            print(f"[Warning] {skip_reason}")
            return False

        if ov_cli_dir.exists() and shutil.which("cargo"):
            print("Building ov CLI from source...")
            try:
                env = self._configure_windows_cargo_env(os.environ.copy())
                build_args = ["cargo", "build", "--release"]
                target = env.get("CARGO_BUILD_TARGET")
                if target:
                    print(f"Cross-compiling with CARGO_BUILD_TARGET={target}")
                    build_args.extend(["--target", target])

                self._run_subprocess(
                    build_args,
                    cwd=str(ov_cli_dir),
                    env=env,
                    error_prefix="Failed to build ov CLI from source",
                )

                cargo_target_dir = self._resolve_cargo_target_dir(ov_cli_dir, env)
                if target:
                    built_bin = cargo_target_dir / target / "release" / binary_name
                else:
                    built_bin = cargo_target_dir / "release" / binary_name

                self._require_artifact(built_bin, binary_name, "ov CLI build")
                self._copy_artifact(built_bin, ov_target_binary)
                print("[OK] ov CLI built successfully from source")
                return True
            except Exception as exc:
                error_msg = str(exc)
                print(f"[Error] {error_msg}")
                raise RuntimeError(error_msg)
        else:
            if ov_target_binary.exists():
                print("[Info] ov CLI binary already exists locally. Skipping source build.")
                return True
            elif not ov_cli_dir.exists():
                print(f"[Warning] ov CLI source directory not found at {ov_cli_dir}")
                return False
            else:
                print("[Warning] Cargo not found. Cannot build ov CLI from source.")
                return False

    def build_extension(self, ext):
        """Build a single Python native extension artifact using CMake."""
        ext_fullpath = Path(self.get_ext_fullpath(ext.name))
        ext_dir = ext_fullpath.parent.resolve()
        build_dir = Path(self.build_temp) / "cmake_build"
        build_dir.mkdir(parents=True, exist_ok=True)

        self._run_stage_with_artifact_checks(
            "CMake build",
            lambda: self._build_extension_impl(ext_fullpath, ext_dir, build_dir),
            [(ext_fullpath, f"native extension '{ext.name}'")],
        )

    def _build_extension_impl(self, ext_fullpath, ext_dir, build_dir):
        """Invoke CMake to build the Python native extension."""
        py_output_name = ext_fullpath.stem
        py_output_suffix = ext_fullpath.suffix

        cmake_args = [
            f"-S{Path(ENGINE_SOURCE_DIR).resolve()}",
            f"-B{build_dir}",
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DPY_OUTPUT_DIR={ext_dir}",
            f"-DPY_OUTPUT_NAME={py_output_name}",
            f"-DPY_OUTPUT_SUFFIX={py_output_suffix}",
            "-DCMAKE_VERBOSE_MAKEFILE=ON",
            "-DCMAKE_INSTALL_RPATH=$ORIGIN",
            f"-DPython3_EXECUTABLE={sys.executable}",
            f"-DPython3_INCLUDE_DIRS={sysconfig.get_path('include')}",
            f"-DPython3_LIBRARIES={sysconfig.get_config_vars().get('LIBRARY')}",
            f"-Dpybind11_DIR={pybind11.get_cmake_dir()}",
            f"-DOV_X86_SIMD_LEVEL={os.environ.get('OV_X86_SIMD_LEVEL', 'AVX2')}",
        ]

        if C_COMPILER_PATH:
            cmake_args.append(f"-DCMAKE_C_COMPILER={C_COMPILER_PATH}")
        if CXX_COMPILER_PATH:
            cmake_args.append(f"-DCMAKE_CXX_COMPILER={CXX_COMPILER_PATH}")

        if sys.platform == "darwin":
            cmake_args.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=10.15")
            target_arch = os.environ.get("CMAKE_OSX_ARCHITECTURES")
            if target_arch:
                cmake_args.append(f"-DCMAKE_OSX_ARCHITECTURES={target_arch}")
        elif sys.platform == "win32":
            cmake_args.extend(self._resolve_windows_cmake_generator_args())

        self.spawn([self.cmake_executable] + cmake_args)

        build_args = ["--build", str(build_dir), "--config", "Release", f"-j{os.cpu_count() or 4}"]
        self.spawn([self.cmake_executable] + build_args)


setup(
    # install_requires=[
    #     f"pyagfs @ file://localhost/{os.path.abspath('third_party/agfs/agfs-sdk/python')}"
    # ],
    ext_modules=[
        Extension(
            name="openviking.storage.vectordb.engine",
            sources=[],
        )
    ],
    cmdclass={
        "build_ext": OpenVikingBuildExt,
    },
    package_data={
        "openviking": [
            "bin/agfs-server",
            "bin/agfs-server.exe",
            "lib/libagfsbinding.so",
            "lib/libagfsbinding.dylib",
            "lib/libagfsbinding.dll",
            "bin/ov",
            "bin/ov.exe",
        ],
    },
    include_package_data=True,
)
