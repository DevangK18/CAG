# discover_docling.py
import pkgutil
import importlib
import sys
from pathlib import Path


def explore_package(package_name: str):
    """
    Dynamically imports and prints the submodule structure of a given package.
    """
    print("-" * 50)
    print(f"🔍 EXPLORING PACKAGE: '{package_name}'")
    print("-" * 50)

    try:
        package = importlib.import_module(package_name)
    except ImportError:
        print(f"❌ ERROR: Could not import the package '{package_name}'.")
        print("Please ensure it is installed correctly in your poetry environment.")
        return

    print(f"✅ Package '{package_name}' imported successfully.")
    print(f"📍 Location: {Path(package.__file__).parent}")
    print("\n📦 Submodule Structure:")

    def find_and_print_submodules(pkg, prefix="  "):
        count = 0
        for finder, name, ispkg in pkgutil.walk_packages(pkg.__path__):
            count += 1
            print(f"{prefix}L- {'📦' if ispkg else '📄'} {name}")
            if ispkg:
                try:
                    sub_pkg = importlib.import_module(f"{pkg.__name__}.{name}")
                    find_and_print_submodules(sub_pkg, prefix + "    ")
                except Exception as e:
                    print(f"{prefix}    L- ⚠️  Could not inspect submodule: {e}")
        if count == 0:
            print(f"{prefix}L- (No submodules found)")

    find_and_print_submodules(package)
    print("-" * 50)


if __name__ == "__main__":
    explore_package("docling_core")
