module regfile (
    input clk,
    input [4:0] rs1,
    input [4:0] rs2,
    input [4:0] rd,
    input [31:0] wdata,
    input we,
    output [31:0] rdata1,
    output [31:0] rdata2
);
    reg [31:0] regs [0:31]; // 32 x 32-bit registers

    // Combinational read logic
    assign rdata1 = (rs1 == 5'd0) ? 32'b0 : regs[rs1];
    assign rdata2 = (rs2 == 5'd0) ? 32'b0 : regs[rs2];

    // Synchronous write logic
    always @(posedge clk) begin
        if (we && (rd != 5'd0)) begin
            regs[rd] <= wdata; // Write data to register
        end
    end
endmodule
