module csr_unit (
    input  wire        clk,
    input  wire        rst,
    input  wire        csr_we,
    input  wire [11:0] csr_addr,
    input  wire [31:0] wdata,
    input  wire [2:0]  funct3,
    output reg  [31:0] rdata,
    output wire        ecall
);

    // CSR addresses
    localparam CSR_MSTATUS = 12'h300;
    localparam CSR_MTVEC   = 12'h305;
    localparam CSR_MHARTID = 12'hF14;
    localparam CSR_MEPC    = 12'h341;
    localparam CSR_MCAUSE  = 12'h342;

    // CSR registers
    reg [31:0] mstatus;
    reg [31:0] mtvec;
    reg [31:0] mepc;
    reg [31:0] mcause;

    // Compute write data based on funct3
    // CSRRW=001, CSRRS=010, CSRRC=011
    reg [31:0] wdata_final;
    always @(*) begin
        case (funct3)
            3'b001: wdata_final = wdata;                // CSRRW
            3'b010: wdata_final = rdata | wdata;        // CSRRS
            3'b011: wdata_final = rdata & ~wdata;       // CSRRC
            3'b101: wdata_final = wdata;                // CSRRWI
            3'b110: wdata_final = rdata | wdata;        // CSRRSI
            3'b111: wdata_final = rdata & ~wdata;       // CSRRCI
            default: wdata_final = wdata;
        endcase
    end

    // Read logic (combinational)
    always @(*) begin
        case (csr_addr)
            CSR_MSTATUS: rdata = mstatus;
            CSR_MTVEC:   rdata = mtvec;
            CSR_MEPC:    rdata = mepc;
            CSR_MCAUSE:  rdata = mcause;
            CSR_MHARTID: rdata = 32'h0;
            default:     rdata = 32'h0;
        endcase
    end

    // Write logic (synchronous)
    always @(posedge clk) begin
        if (rst) begin
            mstatus <= 32'h0;
            mtvec   <= 32'h0;
            mepc    <= 32'h0;
            mcause  <= 32'h0;
        end else if (csr_we) begin
            case (csr_addr)
                CSR_MSTATUS: mstatus <= wdata_final;
                CSR_MTVEC:   mtvec   <= wdata_final;
                CSR_MEPC:    mepc    <= wdata_final;
                CSR_MCAUSE:  mcause  <= wdata_final;
                CSR_MHARTID: ; // writes ignored
                default:     ; // silently ignored
            endcase
        end
    end

    // ECALL detection: funct3=000 indicates ECALL/EBREAK
    // ecall is asserted when csr_we is used with funct3=000 (SYSTEM with funct3=000)
    // Per spec: ecall detected when SYSTEM opcode with funct3=3'b000 and rs1/rd=0
    // We use csr_we as the enable signal from the pipeline
    assign ecall = csr_we && (funct3 == 3'b000);

endmodule