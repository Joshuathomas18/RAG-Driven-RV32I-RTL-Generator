module regfile (
    input  wire        clk,
    input  wire [4:0]  rs1,
    input  wire [4:0]  rs2,
    input  wire [4:0]  rd,
    input  wire [31:0] wdata,
    input  wire        we,
    output wire [31:0] rdata1,
    output wire [31:0] rdata2
);

    reg [31:0] regs [1:31];

    // Synchronous write, gated to prevent writes to x0
    always @(posedge clk) begin
        if (we && rd != 5'd0) begin
            regs[rd] <= wdata;
        end
    end

    // Combinational reads; x0 always returns zero
    assign rdata1 = (rs1 == 5'd0) ? 32'd0 : regs[rs1];
    assign rdata2 = (rs2 == 5'd0) ? 32'd0 : regs[rs2];

endmodule