import os
import subprocess
import sys


def extra_import_dirs(code_dir):
    extras = []
    base = os.path.abspath(os.path.join(code_dir, os.pardir, "product", "frontend"))
    if not os.path.isdir(base):
        return extras
    for name in os.listdir(base):
        lib_root = os.path.join(base, name, "lib")
        if not os.path.isdir(lib_root):
            continue
        for py_name in os.listdir(lib_root):
            py_dir = os.path.join(lib_root, py_name)
            if not os.path.isdir(py_dir):
                continue
            for sub_name in os.listdir(py_dir):
                candidate = os.path.join(py_dir, sub_name)
                if not os.path.isdir(candidate):
                    continue
                has_pkg = False
                for pkg_name in ("mcp", "fastapi", "starlette"):
                    if os.path.isdir(os.path.join(candidate, pkg_name)):
                        has_pkg = True
                        break
                if has_pkg and candidate not in extras:
                    extras.append(candidate)
    return extras


def main():
    code_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    test_files = []

    for root, dirs, files in os.walk(code_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            if file == "run_all_tests.py" or file.startswith('.'):
                continue
            if (file.startswith("test_") and file.endswith(".py")) or file.endswith("_test.py"):
                test_files.append(os.path.join(root, file))

    test_files.sort()

    passed = 0
    failed = 0

    env = os.environ.copy()
    path_parts = [code_dir] + extra_import_dirs(code_dir)
    existing = env.get("PYTHONPATH")
    if existing:
        path_parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(path_parts)

    for test_file in test_files:
        rel_path = os.path.relpath(test_file, start=os.path.dirname(code_dir))
        print(f"Running {rel_path}...")
        result = subprocess.run([sys.executable, test_file], capture_output=True, text=True, env=env)
        if result.returncode == 0:
            print(f"PASS: {rel_path}")
            passed += 1
        else:
            print(f"FAIL: {rel_path}")
            print("--- STDOUT ---")
            print(result.stdout.strip())
            print("--- STDERR ---")
            print(result.stderr.strip())
            failed += 1
            break

    print("\n--- Summary ---")
    print(f"Total tests run: {passed + failed}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
