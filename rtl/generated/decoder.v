module decoder (
    input [31:0] instr,
    output [4:0] rs1,
    output [4:0] rs2,
    output [4:0] rd,
    output [31:0] imm,
    output [3:0] alu_op,
    output alu_src,
    output mem_read,
    output mem_write,
    output [1:0] mem_size,
    output reg_write,
    output [1:0] wb_sel,
    output branch,
    output jump,
    output is_auipc,
    output [2:0] branch_funct3,
    output [2:0] funct3,
    output csr_en,
    output [11:0] csr_addr,
    output [2:0] csr_op,
    output [31:0] csr_wdata
);

    // Default values
    assign rs1 = instr[19:15];
    assign rs2 = instr[24:20];
    assign rd = instr[11:7];
    assign funct3 = instr[14:12];
    assign csr_addr = instr[31:20];
    assign csr_op = instr[14:12];
    assign csr_wdata = (instr[6:0] == 7'b1110011) ? rs1 : 32'b0; // CSR write data
    assign branch = 1'b0;
    assign jump = 1'b0;
    assign is_auipc = 1'b0;
    assign csr_en = 1'b0;
    assign mem_read = 1'b0;
    assign mem_write = 1'b0;
    assign reg_write = 1'b0;
    assign alu_src = 1'b0;
    assign mem_size = 2'b00; // Default to byte size
    assign wb_sel = 2'b00; // Default to ALU output
    assign alu_op = 4'b0000; // Default to ADD operation
    assign imm = 32'b0; // Default immediate

    always @(*) begin
        case (instr[6:0])
            7'b0110011: begin // RTYPE
                reg_write = 1'b1;
                alu_src = 1'b0;
                wb_sel = 2'b00; // ALU result
                alu_op = funct3; // ALU operation based on funct3
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                mem_size = 2'b00;
                csr_en = 1'b0;
            end
            7'b0010011: begin // ITYPE
                reg_write = 1'b1;
                alu_src = 1'b1; // Immediate
                wb_sel = 2'b00; // ALU result
                alu_op = funct3; // ALU operation based on funct3
                imm = {{20{instr[31]}}, instr[31:20]}; // Sign-extend immediate
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                mem_size = 2'b00;
                csr_en = 1'b0;
            end
            7'b0000011: begin // LOAD
                reg_write = 1'b1;
                alu_src = 1'b1; // Immediate
                wb_sel = 2'b01; // Memory result
                mem_read = 1'b1;
                mem_write = 1'b0;
                mem_size = funct3[1:0]; // Load size from funct3
                imm = {{20{instr[31]}}, instr[31:20]}; // Sign-extend immediate
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                csr_en = 1'b0;
            end
            7'b0100011: begin // STORE
                reg_write = 1'b0;
                alu_src = 1'b1; // Immediate
                wb_sel = 2'b00; // Not used
                mem_read = 1'b0;
                mem_write = 1'b1;
                mem_size = funct3[1:0]; // Store size from funct3
                imm = {{20{instr[31]}}, instr[31:25], instr[11:7]}; // Sign-extend immediate
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                csr_en = 1'b0;
            end
            7'b1100011: begin // BRANCH
                reg_write = 1'b0;
                alu_src = 1'b0; // rs2
                wb_sel = 2'b00; // Not used
                branch = 1'b1;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                mem_size = 2'b00;
                imm = {{20{instr[31]}}, instr[7], instr[30:25], instr[11:8], 1'b0}; // Sign-extend immediate
                branch_funct3 = funct3; // Pass funct3 for branch comparison
                alu_op = 4'b0000; // Default ALU operation
                csr_en = 1'b0;
            end
            7'b1101111: begin // JAL
                reg_write = 1'b1;
                alu_src = 1'b0; // Not used
                wb_sel = 2'b10; // PC+4
                imm = {{12{instr[31]}}, instr[19:12], instr[20], instr[30:21], 1'b0}; // Sign-extend immediate
                branch = 1'b0;
                jump = 1'b1;
                is_auipc = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                mem_size = 2'b00;
                csr_en = 1'b0;
            end
            7'b1100111: begin // JALR
                reg_write = 1'b1;
                alu_src = 1'b1; // Immediate
                wb_sel = 2'b10; // PC+4
                imm = {{20{instr[31]}}, instr[31:20]}; // Sign-extend immediate
                branch = 1'b0;
                jump = 1'b1;
                is_auipc = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                mem_size = 2'b00;
                csr_en = 1'b0;
            end
            7'b0110111: begin // LUI
                reg_write = 1'b1;
                alu_src = 1'b0; // Not used
                wb_sel = 2'b00; // ALU result
                imm = {instr[31:12], 12'b0}; // Upper immediate
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                mem_size = 2'b00;
                csr_en = 1'b0;
            end
            7'b0010111: begin // AUIPC
                reg_write = 1'b1;
                alu_src = 1'b0; // Not used
                wb_sel = 2'b10; // PC+4
                imm = {instr[31:12], 12'b0}; // Upper immediate
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b1; // Indicate AUIPC
                mem_read = 1'b0;
                mem_write = 1'b0;
                mem_size = 2'b00;
                csr_en = 1'b0;
            end
            7'b1110011: begin // SYSTEM
                reg_write = 1'b0;
                alu_src = 1'b0; // Not used
                wb_sel = 2'b00; // Not used
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                mem_size = 2'b00;
                csr_en = 1'b1; // Enable CSR
                alu_op = 4'b0000; // Default ALU operation
            end
            default: begin
                // Default case to handle unknown instructions
                reg_write = 1'b0;
                alu_src = 1'b0;
                wb_sel = 2'b00;
                branch = 1'b0;
                jump = 1'b0;
                is_auipc = 1'b0;
                mem_read = 1'b0;
                mem_write = 1'b0;
                mem_size = 2'b00;
                csr_en = 1'b0;
                imm = 32'b0;
                alu_op = 4'b0000;
            end
        endcase
    end

endmodule
