import json
import locale
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pybind11
from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

ENGINE_SOURCE_DIR = "src/"
PROJECT_ROOT = Path(__file__).resolve().parent
BUNDLED_MINGW_ROOT = PROJECT_ROOT / "third_party" / "mingw64"
BUNDLED_MINGW_BIN = BUNDLED_MINGW_ROOT / "bin"
WINDOWS_FALLBACK_MINGW_ROOTS = (
    Path(r"C:\msys64\ucrt64"),
    Path(r"C:\msys64\mingw64"),
)


def _resolve_bundled_tool(tool_name):
    candidate = BUNDLED_MINGW_BIN / tool_name
    if candidate.exists():
        return str(candidate)
    return None


def _resolve_windows_fallback_tool(tool_name):
    if sys.platform != "win32":
        return None

    for root in WINDOWS_FALLBACK_MINGW_ROOTS:
        candidate = root / "bin" / tool_name
        if candidate.exists():
            return str(candidate)
    return None


def _parse_gnu_major_version(tool_path):
    try:
        result = subprocess.run(
            [tool_path, "--version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        return None

    version_output = (result.stdout or result.stderr).splitlines()
    if not version_output:
        return None

    for token in version_output[0].replace("(", " ").replace(")", " ").split():
        parts = token.split(".")
        if parts and parts[0].isdigit():
            return int(parts[0])
    return None


def _prepend_tool_dirs_to_path(path_value, tool_paths):
    seen = set()
    parts = []

    for tool_path in tool_paths:
        if not tool_path:
            continue
        tool_dir = str(Path(tool_path).resolve().parent)
        norm_tool_dir = os.path.normcase(tool_dir)
        if norm_tool_dir in seen:
            continue
        seen.add(norm_tool_dir)
        parts.append(tool_dir)

    for part in path_value.split(os.pathsep):
        if not part:
            continue
        norm_part = os.path.normcase(part)
        if norm_part in seen:
            continue
        seen.add(norm_part)
        parts.append(part)

    return os.pathsep.join(parts)


def _resolve_tool(env_name, tool_name):
    return (
        os.environ.get(env_name)
        or _resolve_bundled_tool(f"{tool_name}.exe" if sys.platform == "win32" else tool_name)
        or _resolve_windows_fallback_tool(
            f"{tool_name}.exe" if sys.platform == "win32" else tool_name
        )
        or shutil.which(tool_name)
        or tool_name
    )


CMAKE_PATH = _resolve_tool("CMAKE", "cmake")
C_COMPILER_PATH = _resolve_tool("CC", "gcc")
CXX_COMPILER_PATH = _resolve_tool("CXX", "g++")

if sys.platform == "win32" and not os.environ.get("CC") and not os.environ.get("CXX"):
    detected_gxx_major = _parse_gnu_major_version(CXX_COMPILER_PATH)
    fallback_gxx = _resolve_windows_fallback_tool("g++.exe")
    fallback_gcc = _resolve_windows_fallback_tool("gcc.exe")
    fallback_gxx_major = _parse_gnu_major_version(fallback_gxx) if fallback_gxx else None

    # Prefer a modern MSYS2 toolchain over the legacy conda-provided GCC 5.x.
    if (
        fallback_gxx
        and fallback_gcc
        and fallback_gxx_major is not None
        and fallback_gxx_major >= 11
        and (detected_gxx_major is None or detected_gxx_major < 11)
    ):
        print(
            "[Info] Switching Windows C/C++ toolchain to "
            f"{fallback_gxx} (detected GCC {fallback_gxx_major})"
        )
        C_COMPILER_PATH = fallback_gcc
        CXX_COMPILER_PATH = fallback_gxx

if sys.platform == "win32":
    os.environ["PATH"] = _prepend_tool_dirs_to_path(
        os.environ.get("PATH", ""),
        (CMAKE_PATH, C_COMPILER_PATH, CXX_COMPILER_PATH),
    )


def _console_safe(text):
    """Return text that can always be printed to the current console."""
    encoding = getattr(sys.stdout, "encoding", None) or locale.getpreferredencoding(False) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


class OpenVikingBuildExt(build_ext):
    """Build OpenViking runtime artifacts and Python native extensions."""

    def run(self):
        self.build_agfs_artifacts()
        if self._should_build_ov_cli():
            self.build_ov_cli_artifact()
        else:
            print("[Info] OV CLI build disabled via OV_DISABLE_OV_CLI=1")
        self.cmake_executable = CMAKE_PATH

        for ext in self.extensions:
            self.build_extension(ext)

    def _should_build_ov_cli(self):
        """Return whether the optional ov CLI artifact should be built."""
        return os.environ.get("OV_DISABLE_OV_CLI") != "1"

    def _should_build_agfs_server(self):
        """Return whether the AGFS server binary should be built."""
        return os.environ.get("OV_DISABLE_AGFS_SERVER") != "1"

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

    def _resolve_python_library(self):
        """Resolve the Windows import library for the active interpreter when available."""
        version_tag = f"python{sys.version_info.major}{sys.version_info.minor}.lib"
        candidates = [
            Path(sys.executable).resolve().parent / "libs" / version_tag,
            Path(sys.base_prefix).resolve() / "libs" / version_tag,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _clear_stale_cmake_cache(self, build_dir):
        """Drop cached CMake state when it points at a different Python interpreter."""
        cache_path = Path(build_dir) / "CMakeCache.txt"
        if not cache_path.exists():
            return

        try:
            cache_text = cache_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"[Warning] Failed to read CMake cache {cache_path}: {exc}")
            return

        current_python = str(Path(sys.executable).resolve()).replace("\\", "/").lower()
        cached_python = None
        for line in cache_text.splitlines():
            if line.startswith("Python3_EXECUTABLE:FILEPATH=") or line.startswith(
                "_Python3_EXECUTABLE:INTERNAL="
            ):
                cached_python = line.split("=", 1)[1].replace("\\", "/").lower()
                break

        if cached_python and cached_python != current_python:
            print(
                "Detected stale CMake Python cache "
                f"({cached_python} != {current_python}); removing {build_dir}"
            )
            shutil.rmtree(build_dir, ignore_errors=True)
            Path(build_dir).mkdir(parents=True, exist_ok=True)

    def _require_artifact(self, artifact_path, artifact_name, stage_name):
        """Abort the build immediately when a required artifact is missing."""
        if artifact_path.exists():
            return
        raise RuntimeError(
            f"{stage_name} did not produce required {artifact_name} at {artifact_path}"
        )

    def _finalize_extension_artifact(self, ext_fullpath, build_dir):
        """Copy fallback CMake output into setuptools' expected extension path."""
        if ext_fullpath.exists():
            return

        fallback_candidates = [
            Path(build_dir) / ext_fullpath.name,
            Path(build_dir) / f"{ext_fullpath.stem}.pyd",
            Path(build_dir) / "Release" / ext_fullpath.name,
            Path(build_dir) / "Release" / f"{ext_fullpath.stem}.pyd",
            Path(build_dir) / "Debug" / ext_fullpath.name,
            Path(build_dir) / "Debug" / f"{ext_fullpath.stem}.pyd",
        ]

        for candidate in fallback_candidates:
            if not candidate.exists():
                continue
            ext_fullpath.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, ext_fullpath)
            print(f"Copied fallback extension artifact from {candidate} to {ext_fullpath}")
            return

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
        require_server_binary = self._should_build_agfs_server()
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
                require_server_binary,
            ),
            ([(agfs_target_binary, binary_name)] if require_server_binary else [])
            + [(agfs_target_lib, lib_name)],
            on_success=lambda: self._copy_artifacts_to_build_lib(
                agfs_target_binary, agfs_target_lib
            ),
        )

    def _build_agfs_artifacts_impl(
        self,
        agfs_server_dir,
        binary_name,
        lib_name,
        agfs_target_binary,
        agfs_target_lib,
        require_server_binary,
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

            if agfs_target_lib.exists() and (not require_server_binary or agfs_target_binary.exists()):
                print(f"[OK] Used pre-built AGFS artifacts from {prebuilt_dir}")
                return

        if os.environ.get("OV_SKIP_AGFS_BUILD") == "1":
            if agfs_target_lib.exists() and (not require_server_binary or agfs_target_binary.exists()):
                print("[OK] Skipping AGFS build, using existing artifacts")
                return
            print("[Warning] OV_SKIP_AGFS_BUILD=1 but artifacts are missing. Will try to build.")

        if agfs_server_dir.exists() and shutil.which("go"):
            print("Building AGFS artifacts from source...")

            if require_server_binary:
                try:
                    print(f"Building AGFS server: {binary_name}")
                    env = os.environ.copy()
                    if "GOOS" in env or "GOARCH" in env:
                        print(
                            f"Cross-compiling with GOOS={env.get('GOOS')} GOARCH={env.get('GOARCH')}"
                        )

                    build_args = (
                        ["go", "build", "-o", f"build/{binary_name}", "cmd/server/main.go"]
                        if sys.platform == "win32"
                        else ["make", "build"]
                    )

                    result = subprocess.run(
                        build_args,
                        cwd=str(agfs_server_dir),
                        env=env,
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    if result.stdout:
                        print(
                            _console_safe(
                                f"Build stdout: {result.stdout.decode('utf-8', errors='replace')}"
                            )
                        )
                    if result.stderr:
                        print(
                            _console_safe(
                                f"Build stderr: {result.stderr.decode('utf-8', errors='replace')}"
                            )
                        )

                    agfs_built_binary = agfs_server_dir / "build" / binary_name
                    self._require_artifact(agfs_built_binary, binary_name, "AGFS server build")
                    self._copy_artifact(agfs_built_binary, agfs_target_binary)
                    print("[OK] AGFS server built successfully from source")
                except Exception as exc:
                    error_msg = f"Failed to build AGFS server from source: {exc}"
                    if isinstance(exc, subprocess.CalledProcessError):
                        if exc.stdout:
                            error_msg += (
                                f"\nBuild stdout:\n{exc.stdout.decode('utf-8', errors='replace')}"
                            )
                        if exc.stderr:
                            error_msg += (
                                f"\nBuild stderr:\n{exc.stderr.decode('utf-8', errors='replace')}"
                            )
                    print(_console_safe(f"[Error] {error_msg}"))
                    raise RuntimeError(error_msg)
            else:
                print("[Info] AGFS server build disabled via OV_DISABLE_AGFS_SERVER=1")

            try:
                print(f"Building AGFS binding library: {lib_name}")
                result = self._build_agfs_binding_library(agfs_server_dir, lib_name)
                if result.stdout:
                    print(_console_safe(f"Build stdout: {result.stdout.decode('utf-8', errors='replace')}"))
                if result.stderr:
                    print(_console_safe(f"Build stderr: {result.stderr.decode('utf-8', errors='replace')}"))

                agfs_built_lib = agfs_server_dir / "build" / lib_name
                self._require_artifact(agfs_built_lib, lib_name, "AGFS binding build")
                self._copy_artifact(agfs_built_lib, agfs_target_lib)
                print("[OK] AGFS binding library built successfully")
            except Exception as exc:
                error_msg = f"Failed to build AGFS binding library: {exc}"
                if isinstance(exc, subprocess.CalledProcessError):
                    if exc.stdout:
                        error_msg += (
                            f"\nBuild stdout: {exc.stdout.decode('utf-8', errors='replace')}"
                        )
                    if exc.stderr:
                        error_msg += (
                            f"\nBuild stderr: {exc.stderr.decode('utf-8', errors='replace')}"
                        )
                print(_console_safe(f"[Error] {error_msg}"))
                raise RuntimeError(error_msg)
        else:
            if agfs_target_lib.exists() and (not require_server_binary or agfs_target_binary.exists()):
                print("[Info] AGFS artifacts already exist locally. Skipping source build.")
            elif not agfs_server_dir.exists():
                print(f"[Warning] AGFS source directory not found at {agfs_server_dir}")
            else:
                print("[Warning] Go compiler not found. Cannot build AGFS from source.")

    def _build_agfs_binding_library(self, agfs_server_dir, lib_name):
        """Build the AGFS binding library using platform-appropriate commands."""
        env = os.environ.copy()
        env["CGO_ENABLED"] = "1"

        if sys.platform == "win32":
            env.setdefault("CC", C_COMPILER_PATH)
            env.setdefault("CXX", CXX_COMPILER_PATH)
            env.setdefault("GOOS", "windows")
            env.setdefault("GOARCH", "amd64")
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

        return subprocess.run(
            build_args,
            cwd=str(agfs_server_dir),
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def build_ov_cli_artifact(self):
        """Build or reuse the ov Rust CLI binary."""
        binary_name = "ov.exe" if sys.platform == "win32" else "ov"
        ov_cli_dir = Path("crates/ov_cli").resolve()
        ov_target_binary = Path("openviking/bin").resolve() / binary_name

        self._run_stage_with_artifact_checks(
            "ov CLI build",
            lambda: self._build_ov_cli_artifact_impl(ov_cli_dir, binary_name, ov_target_binary),
            [(ov_target_binary, binary_name)],
            on_success=lambda: self._copy_artifacts_to_build_lib(ov_target_binary, None),
        )

    def _build_ov_cli_artifact_impl(self, ov_cli_dir, binary_name, ov_target_binary):
        """Implement ov CLI building without final artifact checks."""

        prebuilt_dir = os.environ.get("OV_PREBUILT_BIN_DIR")
        if prebuilt_dir:
            src_bin = Path(prebuilt_dir).resolve() / binary_name
            if src_bin.exists():
                self._copy_artifact(src_bin, ov_target_binary)
                return

        if os.environ.get("OV_SKIP_OV_BUILD") == "1":
            if ov_target_binary.exists():
                print("[OK] Skipping ov CLI build, using existing binary")
                return
            print("[Warning] OV_SKIP_OV_BUILD=1 but binary is missing. Will try to build.")

        if ov_cli_dir.exists() and shutil.which("cargo"):
            print("Building ov CLI from source...")
            try:
                env = os.environ.copy()
                build_args = ["cargo", "build", "--release"]
                target = env.get("CARGO_BUILD_TARGET")
                if target:
                    print(f"Cross-compiling with CARGO_BUILD_TARGET={target}")
                    build_args.extend(["--target", target])

                result = subprocess.run(
                    build_args,
                    cwd=str(ov_cli_dir),
                    env=env,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if result.stdout:
                    print(f"Build stdout: {result.stdout.decode('utf-8', errors='replace')}")
                if result.stderr:
                    print(f"Build stderr: {result.stderr.decode('utf-8', errors='replace')}")

                cargo_target_dir = self._resolve_cargo_target_dir(ov_cli_dir, env)
                if target:
                    built_bin = cargo_target_dir / target / "release" / binary_name
                else:
                    built_bin = cargo_target_dir / "release" / binary_name

                self._require_artifact(built_bin, binary_name, "ov CLI build")
                self._copy_artifact(built_bin, ov_target_binary)
                print("[OK] ov CLI built successfully from source")
            except Exception as exc:
                error_msg = f"Failed to build ov CLI from source: {exc}"
                if isinstance(exc, subprocess.CalledProcessError):
                    if exc.stdout:
                        error_msg += (
                            f"\nBuild stdout: {exc.stdout.decode('utf-8', errors='replace')}"
                        )
                    if exc.stderr:
                        error_msg += (
                            f"\nBuild stderr: {exc.stderr.decode('utf-8', errors='replace')}"
                        )
                print(f"[Error] {error_msg}")
                raise RuntimeError(error_msg)
        else:
            if ov_target_binary.exists():
                print("[Info] ov CLI binary already exists locally. Skipping source build.")
            elif not ov_cli_dir.exists():
                print(f"[Warning] ov CLI source directory not found at {ov_cli_dir}")
            else:
                print("[Warning] Cargo not found. Cannot build ov CLI from source.")

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
            on_success=None,
        )

    def _build_extension_impl(self, ext_fullpath, ext_dir, build_dir):
        """Invoke CMake to build the Python native extension."""
        self._clear_stale_cmake_cache(build_dir)

        py_output_name = ext_fullpath.stem
        py_output_suffix = ext_fullpath.suffix
        python_root = Path(sys.executable).resolve().parent
        python_include = Path(sysconfig.get_path("include")).resolve()
        python_library = self._resolve_python_library()
        python_executable = Path(sys.executable).resolve().as_posix()
        python_root_arg = python_root.as_posix()
        python_include_arg = python_include.as_posix()

        cmake_args = [
            f"-S{Path(ENGINE_SOURCE_DIR).resolve()}",
            f"-B{build_dir}",
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DPY_OUTPUT_DIR={ext_dir}",
            f"-DPY_OUTPUT_NAME={py_output_name}",
            f"-DPY_OUTPUT_SUFFIX={py_output_suffix}",
            "-DCMAKE_VERBOSE_MAKEFILE=ON",
            "-DCMAKE_INSTALL_RPATH=$ORIGIN",
            f"-DPython3_EXECUTABLE={python_executable}",
            f"-DPython3_ROOT_DIR={python_root_arg}",
            f"-DPython_ROOT_DIR={python_root_arg}",
            "-DPython3_FIND_REGISTRY=NEVER",
            "-DPython3_FIND_STRATEGY=LOCATION",
            "-DPython3_FIND_VIRTUALENV=ONLY",
            f"-DPython3_INCLUDE_DIR={python_include_arg}",
            f"-DPython3_INCLUDE_DIRS={python_include_arg}",
            f"-Dpybind11_DIR={pybind11.get_cmake_dir()}",
            f"-DCMAKE_C_COMPILER={C_COMPILER_PATH}",
            f"-DCMAKE_CXX_COMPILER={CXX_COMPILER_PATH}",
            f"-DOV_X86_SIMD_LEVEL={os.environ.get('OV_X86_SIMD_LEVEL', 'AVX2')}",
        ]

        if python_library:
            python_library_arg = python_library.resolve().as_posix()
            cmake_args.append(f"-DPython3_LIBRARY={python_library_arg}")
            cmake_args.append(f"-DPython3_LIBRARIES={python_library_arg}")
            cmake_args.append(f"-DPython3_LIBRARY_RELEASE={python_library_arg}")
        if sys.platform == "darwin":
            cmake_args.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=10.15")
            target_arch = os.environ.get("CMAKE_OSX_ARCHITECTURES")
            if target_arch:
                cmake_args.append(f"-DCMAKE_OSX_ARCHITECTURES={target_arch}")
        elif sys.platform == "win32":
            cmake_args.extend(["-G", "MinGW Makefiles"])
            bundled_make = _resolve_bundled_tool("mingw32-make.exe")
            if bundled_make:
                cmake_args.append(f"-DCMAKE_MAKE_PROGRAM={bundled_make}")

        self.spawn([self.cmake_executable] + cmake_args)

        build_args = ["--build", str(build_dir), "--config", "Release", f"-j{os.cpu_count() or 4}"]
        self.spawn([self.cmake_executable] + build_args)
        self._finalize_extension_artifact(ext_fullpath, build_dir)


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
