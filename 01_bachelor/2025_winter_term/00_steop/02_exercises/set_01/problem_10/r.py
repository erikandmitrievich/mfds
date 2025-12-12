import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

fig, ax = plt.subplots(figsize=(7, 6))

# window [0, 2] × [0, 3] (shaded)
rect_window = Rectangle((0, 0), 2, 3,
                        facecolor='grey', edgecolor='black',
                        linewidth=1.2, alpha=0.4, linestyle='--', zorder=1)
ax.add_patch(rect_window)

# A = [1, 3] × [1, 2] (unshaded, on top)
rect_A = Rectangle((1, 1), 2, 1,
                   facecolor='white', edgecolor='black',
                   linewidth=1.2, alpha=1, zorder=2)
ax.add_patch(rect_A)


# corners
corners = [(1, 1), (1, 2), (3, 1), (3, 2)]
for x, y in corners:
    ax.plot(x, y, 'ko')
    ax.text(x + 0.05, y + 0.05, f'({x}, {y})', fontsize=9)

ax.set_xlim(0, 4)
ax.set_ylim(0, 4)
ax.set_aspect('equal', 'box')
ax.set_xlabel('x axis')
ax.set_ylabel('y axis')
ax.grid(True, linestyle=':', alpha=0.6)

plt.savefig("rectangle_A.png", bbox_inches="tight")
plt.close()
