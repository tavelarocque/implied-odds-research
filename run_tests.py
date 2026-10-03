"""Run every test in tests/. Usage from the project root:  python3 run_tests.py"""
import glob, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
failed = []
for path in sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py"))):
    mod = "tests." + os.path.basename(path)[:-3]
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", mod], cwd=ROOT, capture_output=True, text=True)
    ok = r.returncode == 0
    print(f"{'PASS' if ok else 'FAIL'}  {mod:38} {time.time() - t0:5.1f}s")
    if not ok:
        failed.append(mod)
        print("      " + (r.stdout + r.stderr).strip().replace("\n", "\n      ")[-1500:])
print(f"\n{'all tests passed' if not failed else f'{len(failed)} failed: ' + ', '.join(failed)}")
sys.exit(1 if failed else 0)
