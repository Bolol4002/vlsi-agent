module alu (
    input [3:0] a, b,
    input [2:0] op,
    output reg [3:0] result
);

    always @(*) begin
        case (op)
            3'b000: result = a + b;
            3'b001: result = a - b;
            3'b010: result = a & b;
            3'b011: result = a | b;
            3'b100: result = a ^ b;
            3'b101: result = ~a;
            3'b110: result = (a > b) ? 4'b0001 : 4'b0000;
            3'b111: result = (a == b) ? 4'b0001 : 4'b0000;
            default: result = 4'b0000;
        endcase
    end

endmodule