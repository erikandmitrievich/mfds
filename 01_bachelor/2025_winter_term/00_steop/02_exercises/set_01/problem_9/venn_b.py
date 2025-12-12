# Task:
# Draw an Euler-Venn diagram for
# A \ (B ∩ C)

from matplotlib_venn import venn3, venn3_circles
import matplotlib.pyplot as plt

# make a graph
v = venn3(subsets=(1,1,1,1,1,1,1), set_labels=('A','B','C'),
          set_colors=("orange","blue","red"), alpha=0.5)

# remove subset size labels
for rid in ('100','010','110','001','101','011','111'):
    lbl = v.get_label_by_id(rid)
    if lbl is not None:
        lbl.set_text('')

# highlight A \ (B ∩ C)
regions = [100, 101, 110]
for region in regions:
    patch = v.get_patch_by_id(str(region))
    patch.set_color("limegreen")
    patch.set_alpha(0.7)

# label 100 region
label = v.get_label_by_id('100')
label.set_text("A \\ (B ∩ C)")

plt.savefig("venn-b.png", bbox_inches="tight")
plt.close()
