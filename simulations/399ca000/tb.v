`timescale 1ns/1ps

module tb;
    // DUT signals
    reg  [3:0] a, b;
    reg  [2:0] op;
    wire [3:0] result;

    // Instantiate the ALU
    alu dut (
        .a      (a),
        .b      (b),
        .op     (op),
        .result (result)
    );

    integer test_num;

    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, tb);
        test_num = 0;

        // -------------------------------------------------
        // Test 1 : ADD 3 + 2 = 5
        // -------------------------------------------------
        test_num = test_num + 1;
        a = 4'd3; b = 4'd2; op = 3'b000; #1;
        if (result === 4'b0101)
            $display("Test %0d PASS: ADD   Expected = %b, Got = %b", test_num, 4'b0101, result);
        else
            $display("Test %0d FAIL: ADD   Expected = %b, Got = %b", test_num, 4'b0101, result);
        #10;

        // -------------------------------------------------
        // Test 2 : SUB 5 - 3 = 2
        // -------------------------------------------------
        test_num = test_num + 1;
        a = 4'd5; b = 4'd3; op = 3'b001; #1;
        if (result === 4'b0010)
            $display("Test %0d PASS: SUB   Expected = %b, Got = %b", test_num, 4'b0010, result);
        else
            $display("Test %0d FAIL: SUB   Expected = %b, Got = %b", test_num, 4'b0010, result);
        #10;

        // -------------------------------------------------
        // Test 3 : AND 1010 & 1100 = 1000
        // -------------------------------------------------
        test_num = test_num + 1;
        a = 4'b1010; b = 4'b1100; op = 3'b010; #1;
        if (result === 4'b1000)
            $display("Test %0d PASS: AND   Expected = %b, Got = %b", test_num, 4'b1000, result);
        else
            $display("Test %0d FAIL: AND   Expected = %b, Got = %b", test_num, 4'b1000, result);
        #10;

        // -------------------------------------------------
        // Test 4 : OR 0101 | 0011 = 0111
        // -------------------------------------------------
        test_num = test_num + 1;
        a = 4'b0101; b = 4'b0011; op = 3'b011; #1;
        if (result === 4'b0111)
            $display("Test %0d PASS: OR    Expected = %b, Got = %b", test_num, 4'b0111, result);
        else
            $display("Test %0d FAIL: OR    Expected = %b, Got = %b", test_num, 4'b0111, result);
        #10;

        // -------------------------------------------------
        // Test 5 : XOR 1111 ^ 0000 = 1111
        // -------------------------------------------------
        test_num = test_num + 1;
        a = 4'b1111; b = 4'b0000; op = 3'b100; #1;
        if (result === 4'b1111)
            $display("Test %0d PASS: XOR   Expected = %b, Got = %b", test_num, 4'b1111, result);
        else
            $display("Test %0d FAIL: XOR   Expected = %b, Got = %b", test_num, 4'b1111, result);
        #10;

        // -------------------------------------------------
        // Test 6 : NOT ~0011 = 1100
        // -------------------------------------------------
        test_num = test_num + 1;
        a = 4'b0011; b = 4'bxxxx; op = 3'b101; #1;
        if (result === 4'b1100)
            $display("Test %0d PASS: NOT   Expected = %b, Got = %b", test_num, 4'b1100, result);
        else
            $display("Test %0d FAIL: NOT   Expected = %b, Got = %b", test_num, 4'b1100, result);
        #10;

        // -------------------------------------------------
        // Test 7 : GT 9 > 4 => 1
        // -------------------------------------------------
        test_num = test_num + 1;
        a = 4'd9; b = 4'd4; op = 3'b110; #1;
        if (result === 4'b0001)
            $display("Test %0d PASS: GT    Expected = %b, Got = %b", test_num, 4'b0001, result);
        else
            $display("Test %0d FAIL: GT    Expected = %b, Got = %b", test_num, 4'b0001, result);
        #10;

        // -------------------------------------------------
        // Test 8 : EQ 7 == 7 => 1
        // -------------------------------------------------
        test_num = test_num + 1;
        a = 4'd7; b = 4'd7; op = 3'b111; #1;
        if (result === 4'b0001)
            $display("Test %0d PASS: EQ    Expected = %b, Got = %b", test_num, 4'b0001, result);
        else
            $display("Test %0d FAIL: EQ    Expected = %b, Got = %b", test_num, 4'b0001, result);
        #10;

        // -------------------------------------------------
        // Test 9 : ADD overflow 15 + 1 = 0 (4‑bit wrap)
        // -------------------------------------------------
        test_num = test_num + 1;
        a = 4'd15; b = 4'd1; op = 3'b000; #1;
        if (result === 4'b0000)
            $display("Test %0d PASS: ADD_OVF Expected = %b, Got = %b", test_num, 4'b0000, result);
        else
            $display("Test %0d FAIL: ADD_OVF Expected = %b, Got = %b", test_num, 4'b0000, result);
        #10;

        // -------------------------------------------------
        // Test 10 : SUB underflow 0 - 1 = 15 (4‑bit wrap)
        // -------------------------------------------------
        test_num = test_num + 1;
        a = 4'd0; b = 4'd1; op = 3'b001; #1;
        if (result === 4'b1111)
            $display("Test %0d PASS: SUB_UF Expected = %b, Got = %b", test_num, 4'b1111, result);
        else
            $display("Test %0d FAIL: SUB_UF Expected = %b, Got = %b", test_num, 4'b1111, result);
        #10;

        $finish;
    end
endmodule