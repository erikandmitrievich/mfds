# Example 1

# abstract type Animal end

# struct Cat <: Animal
#     name::String
# end

# struct Dog <: Animal
#     name::String
# end

# speak(a::Cat) = println(a.name, " says meow")
# speak(a::Dog) = println(a.name, " says woof")

# c = Cat("Mittens")
# d = Dog("Doggos")

# speak(c)
# speak(d)


# Example 2

abstract type Shape end

struct Circle <: Shape
    radius::Float64
end

struct Rectangle <: Shape
    height::Float64
    width::Float64
end

area(s::Circle) = π * s.radius^2
area(s::Rectangle) = s.height * s.width

function total_area(shapes::Vector{Shape})
    sum(area(s) for s in shapes)
end

shapes = Vector{Shape}()

push!(shapes, Circle(5.0))
push!(shapes, Rectangle(3.0, 4.0))

println(total_area(shapes))
