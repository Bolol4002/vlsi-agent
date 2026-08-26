`timescale 1ns/1ps

module tb;
    // Signals
    reg  [3:0] a, b;
    reg  [2:0] op;
    wire [3:0] result;

    // Instantiate the DUT
    alu dut (
        .a      (a),
        .b      (b),
        .op     (op),
        .result (result)
    );

    // Dump waveforms
    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, tb);
    end

    // Test procedure
    initial begin
        // Test 0: addition (no overflow)
        a = 4'd5; b = 4'd3; op = 3'b000;
        #10;
        if (result === 4'd8)
            $display("PASS: ADD 5+3 => expected=8, actual=%0d", result);
        else
            $display("FAIL: ADD 5+3 => expected=8, actual=%0d", result);

        // Test 1: addition with overflow (5 + 15 = 20 -> 4'b0100)
        a = 4'd5; b = 4'd15; op = 3'b000;
        #10;
        if (result === 4'd4)
            $display("PASS: ADD overflow 5+15 => expected=4, actual=%0d", result);
        else
            $display("FAIL: ADD overflow 5+15 => expected=4, actual=%0d", result);

        // Test 2: subtraction (7 - 2 = 5)
        a = 4'd7; b = 4'd2; op = 3'b001;
        #10;
        if (result === 4'd5)
            $display("PASS: SUB 7-2 => expected=5, actual=%0d", result);
        else
            $display("FAIL: SUB 7-2 => expected=5, actual=%0d", result);

        // Test 3: subtraction underflow (2 - 7 = -5 -> 4'b1011)
        a = 4'd2; b = 4'd7; op = 3'b001;
        #10;
        if (result === 4'b1011)
            $display("PASS: SUB underflow 2-7 => expected=1011, actual=%b", result);
        else
            $display("FAIL: SUB underflow 2-7 => expected=1011, actual=%b", result);

        // Test 4: bitwise AND (0xA & 0x5 = 0x0)
        a = 4'hA; b = 4'h5; op = 3'b010;
        #10;
        if (result === 4'h0)
            $display("PASS: AND A&5 => expected=0, actual=%b", result);
        else
            $display("FAIL: AND A&5 => expected=0, actual=%b", result);

        // Test 5: bitwise OR (0xA | 0x5 = 0xF)
        a = 4'hA; b = 4'h5; op = 3'b011;
        #10;
        if (result === 4'hF)
            $display("PASS: OR A|5 => expected=F, actual=%b", result);
        else
            $display("FAIL: OR A|5 => expected=F, actual=%b", result);

        // Test 6: bitwise XOR (0xA ^ 0x5 = 0xF)
        a = 4'hA; b = 4'h5; op = 3'b100;
        #10;
        if (result === 4'hF)
            $display("PASS: XOR A^5 => expected=F, actual=%b", result);
        else
            $display("FAIL: XOR A^5 => expected=F, actual=%b", result);

        // Test 7: NOT operation (~A) where A=0x0 => 0xF
        a = 4'h0; b = 4'h0; op = 3'b101;
        #10;
        if (result === 4'hF)
            $display("PASS: NOT ~0 => expected=F, actual=%b", result);
        else
            $display("FAIL: NOT ~0 => expected=F, actual=%b", result);

        // Test 8: Greater-than (A > B) true case (9 > 4)
        a = 4'd9; b = 4'd4; op = 3'b110;
        #10;
        if (result === 4'b0001)
            $display("PASS: GT 9>4 => expected=1, actual=%b", result);
        else
            $display("FAIL: GT 9>4 => expected=1, actual=%b", result);

        // Test 9: Greater-than false case (3 > 7)
        a = 4'd3; b = 4'd7; op = 3'b110;
        #10;
        if (result === 4'b0000)
            $display("PASS: GT 3>7 => expected=0, actual=%b", result);
        else
            $display("FAIL: GT 3>7 => expected=0, actual=%b", result);

        // Test 10: Equality true (5 == 5)
        a = 4'd5; b = 4'd5; op = 3'b111;
        #10;
        if (result === 4'b0001)
            $display("PASS: EQ 5==5 => expected=1, actual=%b", result);
        else
            $display("FAIL: EQ 5==5 => expected=1, actual=%b", result);

        // Test 11: Equality false (2 != 6)
        a = 4'd2; b = 4'd6; op = 3'b111;
        #10;
        if (result === 4'b0000)
            $display("PASS: EQ 2==6 => expected=0, actual=%b", result);
        else
            $display("FAIL: EQ 2==6 => expected=0, actual=%b", result);

        // End simulation
        #10 $finish;
    end
endmodule