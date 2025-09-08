# tools/make_ico.py
from PIL import Image
img = Image.open("assets/nuvana-dark.png").convert("RGBA")
sizes = [(256,256),(128,128),(64,64),(32,32),(16,16)]
img.save("assets/app.ico", sizes=sizes)
print("Wrote assets/app.ico")
