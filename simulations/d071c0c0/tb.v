module tb;
    // Inputs to the DUT
    reg  [3:0] a;
    reg  [3:0] b;
    reg  [2:0] op;
    // Output from the DUT
    wire [3:0] result;

    // Instantiate the ALU
    alu uut (
        .a      (a),
        .b      (b),
        .op     (op),
        .result (result)
    );

    initial begin
        // Dump waveform
        $dumpfile("wave.vcd");
        $dumpvars(0, tb);

        // -------------------------------------------------
        // Test 1 : ADD 3 + 2 = 5
        // -------------------------------------------------
        a = 4'd3; b = 4'd2; op = 3'b000;
        #1;
        if (result === 4'd5)
            $display("PASS: ADD 3+2 => expected 5, got %0d", result);
        else
            $display("FAIL: ADD 3+2 => expected 5, got %0d", result);
        #10;

        // -------------------------------------------------
        // Test 2 : SUB 4 - 1 = 3
        // -------------------------------------------------
        a = 4'd4; b = 4'd1; op = 3'b001;
        #1;
        if (result === 4'd3)
            $display("PASS: SUB 4-1 => expected 3, got %0d", result);
        else
            $display("FAIL: SUB 4-1 => expected 3, got %0d", result);
        #10;

        // -------------------------------------------------
        // Test 3 : AND 1100 & 1010 = 1000
        // -------------------------------------------------
        a = 4'b1100; b = 4'b1010; op = 3'b010;
        #1;
        if (result === 4'b1000)
            $display("PASS: AND 1100&1010 => expected 1000, got %b", result);
        else
            $display("FAIL: AND 1100&1010 => expected 1000, got %b", result);
        #10;

        // -------------------------------------------------
        // Test 4 : OR 0101 | 0011 = 0111
        // -------------------------------------------------
        a = 4'b0101; b = 4'b0011; op = 3'b011;
        #1;
        if (result === 4'b0111)
            $display("PASS: OR 0101|0011 => expected 0111, got %b", result);
        else
            $display("FAIL: OR 0101|0011 => expected 0111, got %b", result);
        #10;

        // -------------------------------------------------
        // Test 5 : XOR 1111 ^ 1010 = 0101
        // -------------------------------------------------
        a = 4'b1111; b = 4'b1010; op = 3'b100;
        #1;
        if (result === 4'b0101)
            $display("PASS: XOR 1111^1010 => expected 0101, got %b", result);
        else
            $display("FAIL: XOR 1111^1010 => expected 0101, got %b", result);
        #10;

        // -------------------------------------------------
        // Test 6 : NOT ~0011 = 1100
        // -------------------------------------------------
        a = 4'b0011; b = 4'bxxxx; op = 3'b101;
        #1;
        if (result === ~4'b0011)
            $display("PASS: NOT ~0011 => expected %b, got %b", ~4'b0011, result);
        else
            $display("FAIL: NOT ~0011 => expected %b, got %b", ~4'b0011, result);
        #10;

        // -------------------------------------------------
        // Test 7 : GT 7 > 5 => 1
        // -------------------------------------------------
        a = 4'd7; b = 4'd5; op = 3'b110;
        #1;
        if (result === 4'b0001)
            $display("PASS: GT 7>5 => expected 1, got %b", result);
        else
            $display("FAIL: GT 7>5 => expected 1, got %b", result);
        #10;

        // -------------------------------------------------
        // Test 8 : EQ 9 == 9 => 1
        // -------------------------------------------------
        a = 4'd9; b = 4'd9; op = 3'b111;
        #1;
        if (result === 4'b0001)
            $display("PASS: EQ 9==9 => expected 1, got %b", result);
        else
            $display("FAIL: EQ 9==9 => expected 1, got %b", result);
        #10;

        // -------------------------------------------------
        // Test 9 : ADD overflow 15 + 1 = 0 (4‑bit wrap)
        // -------------------------------------------------
        a = 4'b1111; b = 4'b0001; op = 3'b000;
        #1;
        if (result === 4'b0000)
            $display("PASS: ADD overflow 15+1 => expected 0000, got %b", result);
        else
            $display("FAIL: ADD overflow 15+1 => expected 0000, got %b", result);
        #10;

        // -------------------------------------------------
        // Test 10 : SUB underflow 0 - 1 = 1111 (4‑bit wrap)
        // -------------------------------------------------
        a = 4'b0000; b = 4'b0001; op = 3'b001;
        #1;
        if (result === 4'b1111)
            $display("PASS: SUB underflow 0-1 => expected 1111, got %b", result);
        else
            $display("FAIL: SUB underflow 0-1 => expected 1111, got %b", result);
        #10;

        $finish;
    end
endmodule