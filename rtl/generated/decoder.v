module decoder (
    input [31:0] instr,
    output [4:0] rs1,
    output [4:0] rs2,
    output [4:0] rd,
    output reg [31:0] imm,
    output reg [3:0] alu_op,
    output reg alu_src,
    output reg mem_read,
    output reg mem_write,
    output reg [1:0] mem_size,
    output reg reg_write,
    output reg [1:0] wb_sel,
    output reg branch,
    output reg jump,
    output reg is_auipc,
    output [2:0] branch_funct3,
    output [2:0] funct3,
    output csr_en,
    output [11:0] csr_addr,
    output [2:0] csr_op,
    output [31:0] csr_wdata
);

    // Default values
    assign rs1 = (instr[6:0] == 7'b0110111) ? 5'b0 : instr[19:15];
    assign rs2 = instr[24:20];
    assign rd = instr[11:7];
    assign funct3 = instr[14:12];
    assign csr_addr = instr[31:20];
    assign csr_op = instr[14:12];
    assign csr_wdata = (instr[6:0] == 7'b1110011) ? {27'b0, rs1} : 32'b0; // SYSTEM opcode for CSR write data
    assign csr_en = (instr[6:0] == 7'b1110011);
    
    reg [3:0] dec_alu_op;
    always @(*) begin
        dec_alu_op = 4'b0000;
        case (instr[6:0])
            7'b0110011: begin // R-type
                case (funct3)
                    3'b000: dec_alu_op = (instr[30] == 1'b1) ? 4'b0001 : 4'b0000; // SUB | ADD
                    3'b001: dec_alu_op = 4'b0111; // SLL
                    3'b010: dec_alu_op = 4'b0101; // SLT
                    3'b011: dec_alu_op = 4'b0110; // SLTU
                    3'b100: dec_alu_op = 4'b0100; // XOR
                    3'b101: dec_alu_op = (instr[30] == 1'b1) ? 4'b1001 : 4'b1000; // SRA | SRL
                    3'b110: dec_alu_op = 4'b0011; // OR
                    3'b111: dec_alu_op = 4'b0010; // AND
                endcase
            end
            7'b0010011: begin // I-type
                case (funct3)
                    3'b000: dec_alu_op = 4'b0000; // ADDI
                    3'b001: dec_alu_op = 4'b0111; // SLLI
                    3'b010: dec_alu_op = 4'b0101; // SLTI
                    3'b011: dec_alu_op = 4'b0110; // SLTIU
                    3'b100: dec_alu_op = 4'b0100; // XORI
                    3'b101: dec_alu_op = (instr[30] == 1'b1) ? 4'b1001 : 4'b1000; // SRAI | SRLI
                    3'b110: dec_alu_op = 4'b0011; // ORI
                    3'b111: dec_alu_op = 4'b0010; // ANDI
                endcase
            end
            default: dec_alu_op = 4'b0000;
        endcase
    end

    // Immediate generation
    always @(*) begin
        case (instr[6:0])
            7'b0110011: begin // RTYPE
                imm = 32'b0;
                alu_src = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                reg_write = 1'b1;
                wb_sel = 2'b00; // ALU result
                alu_op = dec_alu_op; // ALU operation
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_size = 2'b00; // Not used
            end
            7'b0010011: begin // ITYPE
                imm = {{20{instr[31]}}, instr[31:20]}; // I-type immediate
                alu_src = 1'b1;
                mem_read = 1'b0;
                mem_write = 1'b0;
                reg_write = 1'b1;
                wb_sel = 2'b00; // ALU result
                alu_op = dec_alu_op; // ALU operation
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_size = 2'b00; // Not used
            end
            7'b0000011: begin // LOAD
                imm = {{20{instr[31]}}, instr[31:20]}; // I-type immediate
                alu_src = 1'b1;
                mem_read = 1'b1;
                mem_write = 1'b0;
                reg_write = 1'b1;
                wb_sel = 2'b01; // Memory result
                alu_op = 4'b0000; // ALU operation for load
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_size = funct3[1:0]; // Load size
            end
            7'b0100011: begin // STORE
                imm = {{20{instr[31]}}, instr[31:25], instr[11:7]}; // S-type immediate
                alu_src = 1'b1;
                mem_read = 1'b0;
                mem_write = 1'b1;
                reg_write = 1'b0;
                wb_sel = 2'b00; // Not used
                alu_op = 4'b0000; // ALU operation for store
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_size = funct3[1:0]; // Store size
            end
            7'b1100011: begin // BRANCH
                imm = {{20{instr[31]}}, instr[7], instr[30:25], instr[11:8], 1'b0}; // B-type immediate
                alu_src = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                reg_write = 1'b0;
                wb_sel = 2'b00; // Not used
                alu_op = 4'b0000; // ALU operation for branch
                branch = 1'b1;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_size = 2'b00; // Not used
            end
            7'b1101111: begin // JAL
                imm = {{12{instr[31]}}, instr[19:12], instr[20], instr[30:21], 1'b0}; // J-type immediate
                alu_src = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                reg_write = 1'b1;
                wb_sel = 2'b10; // PC+4
                alu_op = 4'b0000; // Not used
                branch = 1'b0;
                jump = 1'b1;
                is_auipc = 1'b0;
                mem_size = 2'b00; // Not used
            end
            7'b1100111: begin // JALR
                imm = {{20{instr[31]}}, instr[31:20]}; // I-type immediate
                alu_src = 1'b1;
                mem_read = 1'b0;
                mem_write = 1'b0;
                reg_write = 1'b1;
                wb_sel = 2'b10; // PC+4
                alu_op = 4'b0000; // Not used
                branch = 1'b0;
                jump = 1'b1;
                is_auipc = 1'b0;
                mem_size = 2'b00; // Not used
            end
            7'b0110111: begin // LUI
                imm = {instr[31:12], 12'b0}; // U-type immediate
                alu_src = 1'b1;
                mem_read = 1'b0;
                mem_write = 1'b0;
                reg_write = 1'b1;
                wb_sel = 2'b00; // ALU result
                alu_op = 4'b0000; // Not used
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_size = 2'b00; // Not used
            end
            7'b0010111: begin // AUIPC
                imm = {instr[31:12], 12'b0}; // U-type immediate
                alu_src = 1'b1;
                mem_read = 1'b0;
                mem_write = 1'b0;
                reg_write = 1'b1;
                wb_sel = 2'b00; // ALU result
                alu_op = 4'b0000; // Not used
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b1; // AUIPC
                mem_size = 2'b00; // Not used
            end
            7'b1110011: begin // SYSTEM
                imm = 32'b0;
                alu_src = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                reg_write = 1'b0;
                wb_sel = 2'b00; // Not used
                alu_op = 4'b0000; // Not used
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_size = 2'b00; // Not used
            end
            default: begin
                imm = 32'b0;
                alu_src = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                reg_write = 1'b0;
                wb_sel = 2'b00; // Not used
                alu_op = 4'b0000; // Not used
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_size = 2'b00; // Not used
            end
        endcase
    end

    assign branch_funct3 = instr[14:12]; // Directly from instruction for branch comparison

endmodule
