module branch_unit (
    input [31:0] pc,
    input [31:0] rs1,
    input [31:0] rs2,
    input [31:0] imm,
    input [2:0] funct3,
    input is_branch,
    input is_jal,
    input is_jalr,
    output reg [31:0] branch_target,
    output reg branch_taken
);

    always @* begin
        // Default values
        branch_target = 32'b0;
        branch_taken = 1'b0;

        if (is_jal) begin
            branch_target = pc + imm; // JAL target calculation
            branch_taken = 1'b1; // JAL is always taken
        end else if (is_jalr) begin
            branch_target = (rs1 + imm) & ~32'h1; // JALR target calculation
            branch_taken = 1'b1; // JALR is always taken
        end else if (is_branch) begin
            case (funct3)
                3'b000: // BEQ
                    branch_taken = (rs1 == rs2);
                3'b001: // BNE
                    branch_taken = (rs1 != rs2);
                3'b100: // BLT
                    branch_taken = ($signed(rs1) < $signed(rs2));
                3'b101: // BGE
                    branch_taken = ($signed(rs1) >= $signed(rs2));
                3'b110: // BLTU
                    branch_taken = (rs1 < rs2);
                3'b111: // BGEU
                    branch_taken = (rs1 >= rs2);
                default: 
                    branch_taken = 1'b0; // Default case
            endcase
            
            if (branch_taken) begin
                branch_target = pc + imm; // Branch target calculation
            end
        end
    end

endmodule
