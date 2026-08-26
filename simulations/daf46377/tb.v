`timescale 1ns/1ps
module tb;
  reg [3:0] a,b;
  reg [2:0] op;
  wire [3:0] result;
  reg [3:0] exp;
  integer pass=0,fail=0;
  alu dut(.a(a),.b(b),.op(op),.result(result));
  initial begin
    $dumpfile("tb.vcd");
    $dumpvars(0,tb);
    // test 1: add
    a=4'd5; b=4'd3; op=3'b000; #1; exp=4'd8; if(result===exp) pass=pass+1; else fail=fail+1;
    // test 2: subtract
    a=4'd9; b=4'd4; op=3'b001; #1; exp=4'd5; if(result===exp) pass=pass+1; else fail=fail+1;
    // test 3: and
    a=4'b1100; b=4'b1010; op=3'b010; #1; exp=4'b1000; if(result===exp) pass=pass+1; else fail=fail+1;
    // test 4: greater than
    a=4'd7; b=4'd2; op=3'b110; #1; exp=4'b0001; if(result===exp) pass=pass+1; else fail=fail+1;
    // test 5: equality
    a=4'd6; b=4'd6; op=3'b111; #1; exp=4'b0001; if(result===exp) pass=pass+1; else fail=fail+1;
    $display("PASS=%0d FAIL=%0d",pass,fail);
    $finish;
  end
endmodule