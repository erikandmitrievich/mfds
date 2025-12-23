using Pkg

# 1. CORE PACKAGES
core_pkgs = [
    "Plots",
    "DataFrames"
]

# 2. RECOMMENDED PACKAGES (Math & Data Science Bachelor)
# These are the industry standards you will likely encounter in your degree.
extra_pkgs = [
    # Data Science & File I/O
    "CSV",                   # Essential for reading/writing .csv files
    "Distributions",         # The gold standard for probability distributions
    "HypothesisTests",       # T-tests, ANOVA, and other standard statistical tests
    "StatsPlots",            # Extension of Plots.jl specifically for DataFrames/Distributions

    # Mathematics & Modeling
    "DifferentialEquations", # Best-in-class solver for ODEs/PDEs (Critical for Math)
    "Symbolics",             # Symbolic mathematics (CAS) - like Wolfram/Mathematica within Julia
    "JuMP",                  # Mathematical Optimization modeling (Linear/Non-linear programming)
    "GLM",                   # Generalized Linear Models (Linear regression, Logistic regression)

    # Machine Learning
    "Flux",                  # The main Deep Learning library in Julia
    "MLJ",                   # A comprehensive Machine Learning framework

    # Productivity Tools
    "Pluto",                 # Interactive, reactive notebooks (simpler/faster than Jupyter)
    "Revise"                 # A lifesaver: updates code without restarting the REPL
]

# Combine lists
all_pkgs = vcat(core_pkgs, extra_pkgs)

# 3. INSTALLATION COMMAND
println("Starting installation of $(length(all_pkgs)) packages...")
Pkg.add(all_pkgs)

println("\nAll packages installed successfully!")
println("List of the installed packages:")

Pkg.status()