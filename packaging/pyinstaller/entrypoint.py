import multiprocessing
from fisheye_ui.app import main

if __name__ == "__main__":
    # Required on Windows
    multiprocessing.freeze_support()
    main()
