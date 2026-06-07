import requests
from io import BytesIO
from PIL import Image, ImageFilter

# Grab a test image (e.g., Bulbasaur from Mega Evolution)
url = "https://images.pokemontcg.io/me1/1_hires.png"
response = requests.get(url)
img = Image.open(BytesIO(response.content))

# Level 1: Impossible (Start of the game)
blur_level_1 = img.filter(ImageFilter.GaussianBlur(radius=40))
blur_level_1.save("hint_1.png")

# Level 2: Hard
blur_level_2 = img.filter(ImageFilter.GaussianBlur(radius=20))
blur_level_2.save("hint_2.png")

# Level 3: Medium (Shapes become visible)
blur_level_3 = img.filter(ImageFilter.GaussianBlur(radius=8))
blur_level_3.save("hint_3.png")

# Level 4: The Art Crop (Final hint)
# Crop a 200x200 square from the center of the artwork
width, height = img.size
left = (width - 200) / 2
top = (height - 300) / 2 # Shifted up slightly to hit the art box, not the text
right = (width + 200) / 2
bottom = (height + 100) / 2
art_crop = img.crop((left, top, right, bottom))
art_crop.save("hint_4_crop.png")

print("Hints generated! Check your folder.")