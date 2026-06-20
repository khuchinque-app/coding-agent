#!/usr/bin/env python3
"""Simple Calculator Application - A basic CLI calculator with support for addition, subtraction, multiplication, division."""


def add(x: float, y: float) -> float:
    """Add two numbers together."""
    return x + y


def subtract(x: float, y: float) -> float:
    """Subtract the second number from the first."""
    return x - y


def multiply(x: float, y: float) -> float:
    """Multiply two numbers together."""
    return x * y


def divide(x: float, y: float) -> float | None:
    """Divide the first number by the second. Returns None if division by zero."""
    if y == 0:
        raise ValueError("Cannot divide by zero!")
    return x / y


def display_menu():
    """Display the calculator menu options."""
    print("\n" + "=" * 40)
    print("         SIMPLE CALCULATOR")
    print("=" * 40)
    print("""
    Available Operations:
      [1] Addition (+)
      [2] Subtraction (-)
      [3] Multiplication (*)
      [4] Division (/)
      [5] Exit

    Please choose an operation (1-5): """)


def get_numbers() -> tuple[float, float]:
    """Prompt user for two numbers."""
    try:
        num1 = float(input("Enter first number: "))
        num2 = float(input("Enter second number: "))
        return num1, num2
    except ValueError as e:
        print(f"Error converting input to float: {e}")
        raise


def perform_operation(operation: str) -> None:
    """Perform the selected operation with user-provided numbers."""
    try:
        num1, num2 = get_numbers()

        if operation == "add":
            result = add(num1, num2)
            print(f"\nResult of {num1} + {num2} = {result}")
        elif operation == "subtract":
            result = subtract(num1, num2)
            print(f"\nResult of {num1} - {num2} = {result}")
        elif operation == "multiply":
            result = multiply(num1, num2)
            print(f"\nResult of {num1} * {num2} = {result}")
        elif operation == "divide":
            try:
                result = divide(num1, num2)
                print(f"\nResult of {num1} / {num2} = {result}")
            except ValueError as e:
                print(f"Error: {e}")

    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")


def main():
    """Main function to run the calculator application."""
    operations = ["add", "subtract", "multiply", "divide"]
    
    while True:
        display_menu()
        
        try:
            choice = input().strip()

            if choice == '5':
                print("\nThank you for using Simple Calculator. Goodbye!")
                break
            
            elif choice in ['1', '2', '3', '4']:
                operation_map = {
                    '1': "add",
                    '2': "subtract",
                    '3': "multiply",
                    '4': "divide"
                }
                perform_operation(operation_map[choice])

            else:
                print("\nInvalid choice! Please select 1-5.")

        except KeyboardInterrupt:
            print("\n\nCalculator closed. Goodbye!")
            break


if __name__ == "__main__":
    main()
