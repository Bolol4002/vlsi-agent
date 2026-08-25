module tb;
    // Signal declarations
    reg  A, B;
    wire Sum, Carry;

    // Instantiate the DUT
    half_adder dut (
        .A    (A),
        .B    (B),
        .Sum  (Sum),
        .Carry(Carry)
    );

    // Task to check results and display PASS/FAIL
    task check;
        input  exp_sum;
        input  exp_carry;
        begin
            if ((Sum === exp_sum) && (Carry === exp_carry))
                $display("PASS: A=%b B=%b => Sum=%b (exp %b), Carry=%b (exp %b)",
                         A, B, Sum, exp_sum, Carry, exp_carry);
            else
                $display("FAIL: A=%b B=%b => Sum=%b (exp %b), Carry=%b (exp %b)",
                         A, B, Sum, exp_sum, Carry, exp_carry);
        end
    endtask

    initial begin
        // Dump waveforms
        $dumpfile("wave.vcd");
        $dumpvars(0, tb);

        // Test case 1: 0 + 0
        A = 0; B = 0;
        #1; check(0,0);
        #10;

        // Test case 2: 0 + 1
        A = 0; B = 1;
        #1; check(1,0);
        #10;

        // Test case 3: 1 + 0
        A = 1; B = 0;
        #1; check(1,0);
        #10;

        // Test case 4: 1 + 1
        A = 1; B = 1;
        #1; check(0,1);
        #10;

        // Test case 5: Random toggle (edge case)
        A = 1'bx; B = 0;
        #1; check(1'bx, 0);
        #10;

        // Test case 6: Both unknown (edge case)
        A = 1'bx; B = 1'bx;
        #1; check(1'bx, 1'bx);
        #10;

        $finish;
    end
endmodule