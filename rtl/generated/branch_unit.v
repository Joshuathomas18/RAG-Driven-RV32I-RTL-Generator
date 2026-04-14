module branch_unit (
    input [31:0] pc,
    input [31:0] rs1,
    input [31:0] rs2,
    input [31:0] imm,
    input [2:0] funct3,
    input is_branch,
    input is_jal,
    input is_jalr,
    output [31:0] branch_target,
    output branch_taken
);

    reg condition_met;
    always @* begin
        case (funct3)
            3'b000: condition_met = (rs1 == rs2);
            3'b001: condition_met = (rs1 != rs2);
            3'b100: condition_met = ($signed(rs1) < $signed(rs2));
            3'b101: condition_met = ($signed(rs1) >= $signed(rs2));
            3'b110: condition_met = (rs1 < rs2);
            3'b111: condition_met = (rs1 >= rs2);
            default: condition_met = 1'b0;
        endcase
    end

    assign branch_taken = is_jal | is_jalr | (is_branch & condition_met);
    assign branch_target = is_jalr ? ((rs1 + imm) & ~32'h1) : (pc + imm);

endmodule
