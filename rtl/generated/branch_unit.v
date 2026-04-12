module branch_unit (
    input  [31:0] pc,
    input  [31:0] rs1,
    input  [31:0] rs2,
    input  [31:0] imm,
    input  [2:0]  funct3,
    input         is_branch,
    input         is_jal,
    input         is_jalr,
    output [31:0] branch_target,
    output        branch_taken
);

    // Branch target computation
    wire [31:0] branch_or_jal_target = pc + imm;
    wire [31:0] jalr_target          = (rs1 + imm) & ~32'h1;

    assign branch_target = is_jalr ? jalr_target : branch_or_jal_target;

    // Conditional branch condition evaluation
    reg cond_met;
    always @(*) begin
        case (funct3)
            3'b000: cond_met = (rs1 == rs2);                              // BEQ
            3'b001: cond_met = (rs1 != rs2);                              // BNE
            3'b100: cond_met = ($signed(rs1) < $signed(rs2));             // BLT
            3'b101: cond_met = ($signed(rs1) >= $signed(rs2));            // BGE
            3'b110: cond_met = (rs1 < rs2);                               // BLTU
            3'b111: cond_met = (rs1 >= rs2);                              // BGEU
            default: cond_met = 1'b0;
        endcase
    end

    assign branch_taken = (is_branch & cond_met) | is_jal | is_jalr;

endmodule