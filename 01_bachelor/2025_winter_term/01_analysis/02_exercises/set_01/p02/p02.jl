using LinearAlgebra

# 1. Define the Metric Function
taxicab_dist(x, y) = return abs(x[1] - y[1]) + abs(x[2] - y[2])

# 2. Define the sequences as functions of n
a(n) = [1/(n+1), 2 + n/(n^2+1)]
b(n) = [sqrt(4+n) - sqrt(n), (-1)^n]

# --- Analyzing a_n ---
println("--- Investigating Sequence a_n ---")
L_a = [0.0, 2.0] # Our hypothesized limit

# Check distance for n = 1 to 5
for n in 1:5
    val = a(n)
    dist = taxicab_dist(val, L_a)
    println("n=$n: value=$val, distance to limit=$dist")
end

# Check huge n
n_large = 10000
dist_large = taxicab_dist(a(n_large), L_a)
println("... n=$n_large: distance to limit = $dist_large (Very close to 0!)")


# --- Analyzing b_n ---
println("\n--- Investigating Sequence b_n ---")

# Let's just look at the raw values to see oscillation
for n in 1:5
    val = b(n)
    println("n=$n: value=$val")
end

println("... n=1000: value=$(b(1000))")
println("... n=1001: value=$(b(1001))")
println("(Notice the second number keeps flipping between 1.0 and -1.0)")
