from PIL import Image
img = Image.new('RGB', (100, 100), (255, 255, 255))
img.save('test_upload.png')
print('created test_upload.png')
