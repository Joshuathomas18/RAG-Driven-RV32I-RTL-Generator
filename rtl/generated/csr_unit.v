module csr_unit (
    input clk,
    input rst,
    input csr_we,
    input [11:0] csr_addr,
    input [31:0] wdata,
    input [2:0] funct3,
    output reg [31:0] rdata,
    output ecall
);

    // CSR addresses
    localparam MSTATUS_ADDR = 12'h300;
    localparam MTVEC_ADDR   = 12'h305;
    localparam MEPC_ADDR    = 12'h341;
    localparam MCAUSE_ADDR  = 12'h342;
    localparam MHARTID_ADDR = 12'hF14;

    // ECALL detection
    assign ecall = (funct3 == 3'b000) && (csr_addr == 12'h300) && csr_we;

    // CSR read logic
    always @(*) begin
        rdata = 32'h0; // Default read value
        case (csr_addr)
            MSTATUS_ADDR: rdata = 32'h0; // Read mstatus
            MTVEC_ADDR:   rdata = 32'h0; // Read mtvec
            MEPC_ADDR:    rdata = 32'h0; // Read mepc
            MCAUSE_ADDR:  rdata = 32'h0; // Read mcause
            MHARTID_ADDR: rdata = 32'h0; // Read mhartid (always returns 0)
            default:      rdata = 32'h0; // All other CSRs return 0
        endcase
    end

    // CSR write logic
    always @(posedge clk) begin
        if (rst) begin
            // Reset logic can be added here if needed
        end else if (csr_we) begin
            // Writes are silently accepted, no action needed
            // For mhartid, writes are ignored
        end
    end

endmodule
