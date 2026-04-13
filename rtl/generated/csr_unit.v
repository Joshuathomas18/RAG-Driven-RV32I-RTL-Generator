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
    localparam MTVEC_ADDR = 12'h305;
    localparam MEPC_ADDR = 12'h341;
    localparam MCAUSE_ADDR = 12'h342;
    localparam MHARTID_ADDR = 12'hF14;

    // ECALL detection
    assign ecall = (csr_addr == MSTATUS_ADDR && funct3 == 3'b000 && csr_we);

    // CSR registers
    reg [31:0] mstatus;
    reg [31:0] mtvec;
    reg [31:0] mepc;
    reg [31:0] mcause;

    // Read data logic
    always @(*) begin
        case (csr_addr)
            MSTATUS_ADDR: rdata = mstatus;
            MTVEC_ADDR: rdata = mtvec;
            MEPC_ADDR: rdata = mepc;
            MCAUSE_ADDR: rdata = mcause;
            MHARTID_ADDR: rdata = 32'h0; // Always return 0 for mhartid
            default: rdata = 32'h0; // All other CSRs return 0
        endcase
    end

    // Write logic
    always @(posedge clk) begin
        if (rst) begin
            mstatus <= 32'h0;
            mtvec <= 32'h0;
            mepc <= 32'h0;
            mcause <= 32'h0;
        end else if (csr_we) begin
            case (csr_addr)
                MSTATUS_ADDR: mstatus <= wdata; // Write to mstatus
                MTVEC_ADDR: mtvec <= wdata; // Write to mtvec
                MEPC_ADDR: mepc <= wdata; // Write to mepc
                MCAUSE_ADDR: mcause <= wdata; // Write to mcause
                MHARTID_ADDR: ; // Ignore writes to mhartid
                default: ; // Ignore writes to unimplemented CSRs
            endcase
        end
    end

endmodule
