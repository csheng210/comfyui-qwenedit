import os
from pathlib import Path
os.chdir(r"C:\Users\Administrator\Documents\comfyui-qwenedit\_selftest_dir")
print("relative input/sofa.png ->", Path("input/sofa.png").is_file())
print("bare sofa.png via input/ ->", (Path("input") / Path("sofa.png").name).is_file())