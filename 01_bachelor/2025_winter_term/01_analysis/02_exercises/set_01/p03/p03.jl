# 1. Approximate the limit 'a' of the Alternating Harmonic Series
# We use a large N because this series converges very slowly.
function calc_a(N)
    sum_val = 0.0
    for n in 1:N
        term = ((-1)^(n+1)) / n
        sum_val += term
    end
    return sum_val
end

# Calculate a with 100,000 iterations
a_approx = calc_a(100000)
println("Approximation of a (approx ln(2)): $a_approx")
println("Actual value of ln(2): ", log(2))
println("Difference: ", abs(a_approx - log(2)))

println("\n--------------------------------\n")

# 2. Approximate the second series using our calculated 'a_approx'
# This is sum( a^k / k! )
function calc_exponential_series(val, K_max)
    sum_val = 0.0
    for k in 0:K_max
        # Note: In Julia, factorial(k) grows very fast.
        # For floating point math, 20 terms is usually enough for precision.
        term = (val^k) / factorial(big(k))
        sum_val += term
    end
    return sum_val
end

# We only need about 20 terms for the exponential series to converge
final_result = calc_exponential_series(a_approx, 20)

println("Result of sum( a^k / k! ): $final_result")
println("Is the result 2? ", isapprox(Float64(final_result), 2.0, atol=1e-4))
