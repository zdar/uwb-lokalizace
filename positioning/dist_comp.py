
import math


d  = 90
d1 = 95
d2 = 117
a  = (d1**2 - d2**2 + d**2) / (2 * d)
h  = math.sqrt(abs(d1**2 - a**2))
x  = a
y  = h       # or -h; pick the sign that matches where you physically placed A3
print(f"Calculated position: ({x:.2f}, {y:.2f})")