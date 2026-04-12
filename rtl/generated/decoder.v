module decoder (
    input  [31:0] inst,
    output [4:0]  rs1,
    output [4:0]  rs2,
    output [4:0]  rd,
    output reg [31:0] imm,
    output reg [3:0]  alu_op,
    output reg        alu_src,
    output reg        mem_read,
    output reg        mem_write,
    output reg [1:0]  mem_size,
    output reg        reg_write,
    output reg [1:0]  wb_sel,
    output reg        branch,
    output reg        jump,
    output reg        is_auipc,
    output [2:0]      branch_funct3
);

    // Opcode constants
    localparam RTYPE  = 7'b0110011;
    localparam ITYPE  = 7'b0010011;
    localparam LOAD   = 7'b0000011;
    localparam STORE  = 7'b0100011;
    localparam BRANCH = 7'b1100011;
    localparam JAL    = 7'b1101111;
    localparam JALR   = 7'b1100111;
    localparam LUI    = 7'b0110111;
    localparam AUIPC  = 7'b0010111;
    localparam SYSTEM = 7'b1110011;
    localparam FENCE  = 7'b0001111;

    // ALU op constants
    localparam ALU_ADD  = 4'b0000;
    localparam ALU_SUB  = 4'b0001;
    localparam ALU_AND  = 4'b0010;
    localparam ALU_OR   = 4'b0011;
    localparam ALU_XOR  = 4'b0100;
    localparam ALU_SLT  = 4'b0101;
    localparam ALU_SLTU = 4'b0110;
    localparam ALU_SLL  = 4'b0111;
    localparam ALU_SRL  = 4'b1000;
    localparam ALU_SRA  = 4'b1001;

    // Fixed field extractions
    assign rs1          = inst[19:15];
    assign rs2          = inst[24:20];
    assign rd           = inst[11:7];
    assign branch_funct3 = inst[14:12];

    wire [6:0] opcode  = inst[6:0];
    wire [2:0] funct3  = inst[14:12];
    wire [6:0] funct7  = inst[31:25];

    always @(*) begin
        // Defaults
        imm       = 32'b0;
        alu_op    = ALU_ADD;
        alu_src   = 1'b0;
        mem_read  = 1'b0;
        mem_write = 1'b0;
        mem_size  = 2'b10;
        reg_write = 1'b0;
        wb_sel    = 2'b00;
        branch    = 1'b0;
        jump      = 1'b0;
        is_auipc  = 1'b0;

        case (opcode)
            RTYPE: begin
                imm       = 32'b0;
                alu_src   = 1'b0;
                reg_write = 1'b1;
                wb_sel    = 2'b00;
                case ({funct7, funct3})
                    10'b0000000_000: alu_op = ALU_ADD;
                    10'b0100000_000: alu_op = ALU_SUB;
                    10'b0000000_001: alu_op = ALU_SLL;
                    10'b0000000_010: alu_op = ALU_SLT;
                    10'b0000000_011: alu_op = ALU_SLTU;
                    10'b0000000_100: alu_op = ALU_XOR;
                    10'b0000000_101: alu_op = ALU_SRL;
                    10'b0100000_101: alu_op = ALU_SRA;
                    10'b0000000_110: alu_op = ALU_OR;
                    10'b0000000_111: alu_op = ALU_AND;
                    default:         alu_op = ALU_ADD;
                endcase
            end

            ITYPE: begin
                // I-type immediate
                imm       = {{20{inst[31]}}, inst[31:20]};
                alu_src   = 1'b1;
                reg_write = 1'b1;
                wb_sel    = 2'b00;
                case (funct3)
                    3'b000: alu_op = ALU_ADD;  // ADDI
                    3'b010: alu_op = ALU_SLT;  // SLTI
                    3'b011: alu_op = ALU_SLTU; // SLTIU
                    3'b100: alu_op = ALU_XOR;  // XORI
                    3'b110: alu_op = ALU_OR;   // ORI
                    3'b111: alu_op = ALU_AND;  // ANDI
                    3'b001: alu_op = ALU_SLL;  // SLLI
                    3'b101: begin
                        if (funct7[5])
                            alu_op = ALU_SRA; // SRAI
                        else
                            alu_op = ALU_SRL; // SRLI
                    end
                    default: alu_op = ALU_ADD;
                endcase
            end

            LOAD: begin
                // I-type immediate
                imm       = {{20{inst[31]}}, inst[31:20]};
                alu_src   = 1'b1;
                mem_read  = 1'b1;
                reg_write = 1'b1;
                wb_sel    = 2'b01;
                alu_op    = ALU_ADD;
                case (funct3)
                    3'b000: mem_size = 2'b00; // LB
                    3'b001: mem_size = 2'b01; // LH
                    3'b010: mem_size = 2'b10; // LW
                    3'b100: mem_size = 2'b00; // LBU
                    3'b101: mem_size = 2'b01; // LHU
                    default: mem_size = 2'b10;
                endcase
            end

            STORE: begin
                // S-type immediate
                imm       = {{20{inst[31]}}, inst[31:25], inst[11:7]};
                alu_src   = 1'b1;
                mem_write = 1'b1;
                reg_write = 1'b0;
                wb_sel    = 2'b00;
                alu_op    = ALU_ADD;
                case (funct3)
                    3'b000: mem_size = 2'b00; // SB
                    3'b001: mem_size = 2'b01; // SH
                    3'b010: mem_size = 2'b10; // SW
                    default: mem_size = 2'b10;
                endcase
            end

            BRANCH: begin
                // B-type immediate
                imm       = {{19{inst[31]}}, inst[31], inst[7], inst[30:25], inst[11:8], 1'b0};
                alu_src   = 1'b0;
                branch    = 1'b1;
                reg_write = 1'b0;
                wb_sel    = 2'b00;
                alu_op    = ALU_ADD; // ALU computes branch target (PC + imm)
            end

            JAL: begin
                // J-type immediate
                imm       = {{11{inst[31]}}, inst[31], inst[19:12], inst[20], inst[30:21], 1'b0};
                alu_src   = 1'b1;
                jump      = 1'b1;
                reg_write = 1'b1;
                wb_sel    = 2'b10; // PC+4
                alu_op    = ALU_ADD;
            end

            JALR: begin
                // I-type immediate
                imm       = {{20{inst[31]}}, inst[31:20]};
                alu_src   = 1'b1;
                jump      = 1'b1;
                reg_write = 1'b1;
                wb_sel    = 2'b10; // PC+4
                alu_op    = ALU_ADD;
            end

            LUI: begin
                // U-type immediate
                imm       = {inst[31:12], 12'b0};
                alu_src   = 1'b1;
                reg_write = 1'b1;
                wb_sel    = 2'b00;
                alu_op    = ALU_ADD;
                // LUI: rd = imm (ALU: 0 + imm, but we use rs1=x0 effectively)
                // Actually for LUI, we want rd = imm directly
                // We'll pass imm as operand B, and rs1=x0 gives 0+imm=imm
            end

            AUIPC: begin
                // U-type immediate
                imm       = {inst[31:12], 12'b0};
                alu_src   = 1'b1;
                reg_write = 1'b1;
                wb_sel    = 2'b00;
                alu_op    = ALU_ADD;
                is_auipc  = 1'b1;
            end

            SYSTEM: begin
                // I-type immediate (CSR address in upper 12 bits)
                imm       = {{20{inst[31]}}, inst[31:20]};
                alu_src   = 1'b1;
                reg_write = 1'b1;
                wb_sel    = 2'b11; // CSR
                alu_op    = ALU_ADD;
            end

            FENCE: begin
                // NOP-like
                imm       = 32'b0;
                alu_src   = 1'b0;
                reg_write = 1'b0;
                wb_sel    = 2'b00;
                alu_op    = ALU_ADD;
            end

            default: begin
                imm       = 32'b0;
                alu_op    = ALU_ADD;
                alu_src   = 1'b0;
                mem_read  = 1'b0;
                mem_write = 1'b0;
                mem_size  = 2'b10;
                reg_write = 1'b0;
                wb_sel    = 2'b00;
                branch    = 1'b0;
                jump      = 1'b0;
                is_auipc  = 1'b0;
            end
        endcase
    end

endmodule