import matplotlib
matplotlib.use('Agg')  
import matplotlib.pyplot as plt

# Paste your current ANL registry coordinates here
anchors = [
    {"id": 0, "x": 0.00,   "y": 0.00,   "z": 0.00,  "label": "ANL (A0)"},
    {"id": 4, "x": 70.00, "y": 0.00,   "z": 0.00,  "label": "A4"},
    {"id": 3, "x": -0.32, "y": 96.00,  "z": 0.00,  "label": "A3"},
    {"id": 2, "x": 41.54,  "y": -84.33, "z": 0.00,  "label": "A2"},
]

fig, ax = plt.subplots(figsize=(6, 6))

for a in anchors:
    color = "red" if a["id"] == 0 else "blue"
    ax.plot(a["x"], a["y"], "o", markersize=12, color=color)
    ax.annotate(
        f'{a["label"]}\n({a["x"]:.1f}, {a["y"]:.1f}, {a["z"]:.1f})',
        (a["x"], a["y"]),
        textcoords="offset points",
        xytext=(0, 12),
        ha="center",
        fontsize=9,
    )

# # Connect them with thin grey lines so you can eyeball the shape
# xs = [a["x"] for a in anchors] + [anchors[0]["x"]]
# ys = [a["y"] for a in anchors] + [anchors[0]["y"]]
# ax.plot(xs, ys, "-", color="grey", alpha=0.4, linewidth=1)

ax.set_aspect("equal", adjustable="box")
ax.set_xlabel("X")
ax.set_ylabel("Y")
ax.set_title("UWB Anchor Positions from ANL Registry")
ax.grid(True, linestyle="--", alpha=0.4)
plt.tight_layout()
plt.savefig('anchors.png', dpi=150)
print("Saved plot to anchors.png")