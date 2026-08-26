`timescale 1ns/1ps

module tb;
    // Signals
    reg  [3:0] a, b;
    reg  [2:0] op;
    wire [3:0] result;

    // Instantiate the DUT
    alu dut (
        .a(a),
        .b(b),
        .op(op),
        .result(result)
    );

    // Dump waveforms
    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, tb);
    end

    // Task to check result and display PASS/FAIL
    task check;
        input [3:0] exp;
        begin
            if (result === exp)
                $display("PASS: op=%b a=%0d b=%0d => expected=%0d, actual=%0d",
                         op, a, b, exp, result);
            else
                $display("FAIL: op=%b a=%0d b=%0d => expected=%0d, actual=%0d",
                         op, a, b, exp, result);
        end
    endtask

    // Test sequence
    initial begin
        // Test 1: ADD (0) 3 + 5 = 8
        a = 4'd3; b = 4'd5; op = 3'b000; #10;
        check(4'd8);

        // Test 2: SUB (1) 9 - 4 = 5
        a = 4'd9; b = 4'd4; op = 3'b001; #10;
        check(4'd5);

        // Test 3: AND (2) 0xA & 0xC = 0x8
        a = 4'hA; b = 4'hC; op = 3'b010; #10;
        check(4'h8);

        // Test 4: OR (3) 0x5 | 0x2 = 0x7
        a = 4'h5; b = 4'h2; op = 3'b011; #10;
        check(4'h7);

        // Test 5: XOR (4) 0xF ^ 0x0 = 0xF
        a = 4'hF; b = 4'h0; op = 3'b100; #10;
        check(4'hF);

        // Test 6: NOT (5) ~0x3 = 0xC
        a = 4'h3; b = 4'h0; op = 3'b101; #10;
        check(4'hC);

        // Test 7: GREATER THAN (6) 7 > 2 => 1
        a = 4'd7; b = 4'd2; op = 3'b110; #10;
        check(4'b0001);

        // Test 8: EQUAL (7) 5 == 5 => 1, then 5 == 6 => 0
        a = 4'd5; b = 4'd5; op = 3'b111; #10;
        check(4'b0001);
        a = 4'd5; b = 4'd6; op = 3'b111; #10;
        check(4'b0000);

        // Edge case: overflow on addition (15 + 1 = 0 due to 4‑bit wrap)
        a = 4'd15; b = 4'd1; op = 3'b000; #10;
        check(4'd0);

        $finish;
    end
endmodule