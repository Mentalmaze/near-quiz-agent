#!/usr/bin/env python3
"""
Test script to verify the floating point precision fix for NEAR amount validation.
"""

# Simulate the calculation logic from blockchain.py
NEAR = 10**24  # 1 NEAR = 10^24 yoctoNEAR


def test_amount_validation():
    """Test the amount validation logic with the precision fix."""

    # Test case from the log: 1.0200 NEAR requirement
    required_amount = 1.0  # Base amount
    required_amount_with_fee = round(required_amount * 1.02, 6)  # 1.02 NEAR
    required_yocto_with_fee = int(required_amount_with_fee * NEAR)

    # Simulate deposited amount that should be exactly enough
    deposited_near = 1.02
    total_yocto = int(deposited_near * NEAR)

    tolerance_yocto = 1000  # Our tolerance fix

    print(f"Required amount: {required_amount} NEAR")
    print(f"Required with fee: {required_amount_with_fee} NEAR")
    print(f"Required in yoctoNEAR: {required_yocto_with_fee}")
    print(f"Deposited amount: {deposited_near} NEAR")
    print(f"Deposited in yoctoNEAR: {total_yocto}")
    print(f"Difference: {total_yocto - required_yocto_with_fee} yoctoNEAR")

    # Old logic (would fail)
    old_logic_passes = total_yocto >= required_yocto_with_fee
    print(f"Old logic (>=): {old_logic_passes}")

    # New logic (should pass)
    new_logic_passes = total_yocto >= (required_yocto_with_fee - tolerance_yocto)
    print(f"New logic (>= with tolerance): {new_logic_passes}")

    # Test edge cases
    print("\n--- Edge Cases ---")

    # Exactly matching amounts
    test_cases = [
        (1.0, 1.02),  # Exact match
        (1.0, 1.019999),  # Slightly under
        (1.0, 1.020001),  # Slightly over
        (2.5, 2.55),  # Larger exact match
    ]

    for base, deposited in test_cases:
        required_with_fee = round(base * 1.02, 6)
        required_yocto = int(required_with_fee * NEAR)
        deposited_yocto = int(deposited * NEAR)

        old_passes = deposited_yocto >= required_yocto
        new_passes = deposited_yocto >= (required_yocto - tolerance_yocto)

        print(f"Base: {base} NEAR, Deposited: {deposited} NEAR")
        print(
            f"  Required: {required_yocto} yoctoNEAR, Deposited: {deposited_yocto} yoctoNEAR"
        )
        print(f"  Diff: {deposited_yocto - required_yocto} yoctoNEAR")
        print(f"  Old logic: {old_passes}, New logic: {new_passes}")
        print()


if __name__ == "__main__":
    test_amount_validation()
