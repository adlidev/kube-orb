"""Allows `python -m kube_illume` to work alongside the `kube-illume` script."""
from .cli import main

if __name__ == "__main__":
    main()
