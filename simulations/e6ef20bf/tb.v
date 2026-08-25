`timescale 1ns/1ps

module tb;
    // DUT signals
    reg  [3:0] a;
    reg  [3:0] b;
    reg  [2:0] op;
    wire [3:0] result;

    // Instantiate the ALU
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

    // Test task
    task run_test;
        input [3:0]  a_in;
        input [3:0]  b_in;
        input [2:0]  op_in;
        input [3:0]  exp;
        input integer test_num;
        begin
            a  = a_in;
            b  = b_in;
            op = op_in;
            #1; // allow combinational logic to settle
            if (result === exp)
                $display("Test %0d PASS: op=%b a=%b b=%b Expected=%b Actual=%b",
                         test_num, op, a, b, exp, result);
            else
                $display("Test %0d FAIL: op=%b a=%b b=%b Expected=%b Actual=%b",
                         test_num, op, a, b, exp, result);
            #10;
        end
    endtask

    // Testbench stimulus
    initial begin
        // Test 1: ADD (no overflow)
        run_test(4'd3, 4'd4, 3'b000, 4'd7, 1);

        // Test 2: ADD (overflow, wraps around 4 bits)
        run_test(4'd15, 4'd1, 3'b000, 4'd0, 2);

        // Test 3: SUB (positive result)
        run_test(4'd9, 4'd5, 3'b001, 4'd4, 3);

        // Test 4: SUB (negative result wraps)
        run_test(4'd2, 4'd5, 3'b001, 4'd13, 4); // 2-5 = -3 => 4'b1101

        // Test 5: AND
        run_test(4'b1010, 4'b1100, 3'b010, 4'b1000, 5);

        // Test 6: OR
        run_test(4'b0101, 4'b0011, 3'b011, 4'b0111, 6);

        // Test 7: XOR
        run_test(4'b1111, 4'b1010, 3'b100, 4'b0101, 7);

        // Test 8: NOT
        run_test(4'b0011, 4'bxxxx, 3'b101, 4'b1100, 8);

        // Test 9: Greater-than (true)
        run_test(4'd9, 4'd3, 3'b110, 4'b0001, 9);

        // Test 10: Greater-than (false)
        run_test(4'd2, 4'd7, 3'b110, 4'b0000, 10);

        // Test 11: Equality (true)
        run_test(4'd5, 4'd5, 3'b111, 4'b0001, 11);

        // Test 12: Equality (false)
        run_test(4'd5, 4'd6, 3'b111, 4'b0000, 12);

        $finish;
    end
endmodule