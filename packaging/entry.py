import multiprocessing
import sys

from html_video_workflow.cli.main import main

if __name__ == "__main__":
    # PyInstaller's onedir build starts child processes for its own bootstrap;
    # without this a frozen Windows build can re-run the whole application in
    # every child.
    multiprocessing.freeze_support()
    sys.exit(main())
