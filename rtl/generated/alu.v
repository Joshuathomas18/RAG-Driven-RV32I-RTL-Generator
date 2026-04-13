module alu (
    input [31:0] a,
    input [31:0] b,
    input [3:0] alu_op,
    output reg [31:0] result,
    output zero
);

always @(*) begin
    result = 32'b0; // Default result
    case (alu_op)
        4'b0000: result = a + b;                // ADD
        4'b0001: result = a - b;                // SUB
        4'b0010: result = a & b;                // AND
        4'b0011: result = a | b;                // OR
        4'b0100: result = a ^ b;                // XOR
        4'b0101: result = ($signed(a) < $signed(b)) ? 32'b1 : 32'b0; // SLT
        4'b0110: result = (a < b) ? 32'b1 : 32'b0; // SLTU
        4'b0111: result = b << a[4:0];          // SLL
        4'b1000: result = b >> a[4:0];          // SRL
        4'b1001: result = $signed(b) >>> a[4:0]; // SRA
        default: result = 32'b0; // Default case
    endcase
end

assign zero = (result == 32'b0);

endmodule
