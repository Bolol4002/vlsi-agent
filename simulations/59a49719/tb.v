module tb;
    // Signals
    reg  [3:0] a, b;
    reg  [2:0] op;
    wire [3:0] result;

    // Instantiate DUT
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

    // Task to check result and display PASS/FAIL
    task check;
        input [3:0] exp;
        begin
            if (result === exp)
                $display("PASS: op=%b a=%0d b=%0d => result=%0d (expected %0d)", op, a, b, result, exp);
            else
                $display("FAIL: op=%b a=%0d b=%0d => result=%0d (expected %0d)", op, a, b, result, exp);
        end
    endtask

    // Test sequence
    initial begin
        // Test 1: ADD (no overflow)
        a  = 4'd3; b = 4'd4; op = 3'b000; #10;
        check(4'd7);

        // Test 2: ADD (overflow, wraps around 4-bit)
        a  = 4'd15; b = 4'd1; op = 3'b000; #10;
        check(4'd0);

        // Test 3: SUB (positive result)
        a  = 4'd9; b = 4'd5; op = 3'b001; #10;
        check(4'd4);

        // Test 4: SUB (underflow, wraps)
        a  = 4'd2; b = 4'd5; op = 3'b001; #10;
        check(4'd13); // 2-5 = -3 -> 4'b1101

        // Test 5: AND
        a  = 4'b1010; b = 4'b1100; op = 3'b010; #10;
        check(4'b1000);

        // Test 6: OR
        a  = 4'b0101; b = 4'b0011; op = 3'b011; #10;
        check(4'b0111);

        // Test 7: XOR
        a  = 4'b1111; b = 4'b0000; op = 3'b100; #10;
        check(4'b1111);

        // Test 8: NOT
        a  = 4'b0011; b = 4'bxxxx; op = 3'b101; #10;
        check(~4'b0011);

        // Test 9: Greater-than (true)
        a  = 4'd9; b = 4'd3; op = 3'b110; #10;
        check(4'b0001);

        // Test 10: Greater-than (false)
        a  = 4'd2; b = 4'd7; op = 3'b110; #10;
        check(4'b0000);

        // Test 11: Equality (true)
        a  = 4'd5; b = 4'd5; op = 3'b111; #10;
        check(4'b0001);

        // Test 12: Equality (false)
        a  = 4'd8; b = 4'd3; op = 3'b111; #10;
        check(4'b0000);

        // End simulation
        $finish;
    end
endmodule