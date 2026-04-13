module pipeline_regs (
    input clk,
    input rst,
    input stall_if_id,
    input flush_if_id,
    input stall_id_ex,
    input flush_id_ex,
    input flush_ex_mem,
    input [31:0] if_pc,
    input [31:0] if_instr,
    input [31:0] id_rs1_data,
    input [31:0] id_rs2_data,
    input [4:0] id_rs1_addr,
    input [4:0] id_rs2_addr,
    input [4:0] id_rd_addr,
    input [31:0] id_imm,
    input [3:0] id_alu_op,
    input id_alu_src,
    input id_mem_write,
    input id_mem_read,
    input [1:0] id_wb_sel,
    input id_reg_write,
    input id_branch,
    input id_jump,
    input [2:0] id_branch_funct3,
    input id_is_auipc,
    input [31:0] id_pc_plus4,
    input [31:0] ex_alu_result,
    input [31:0] ex_rs2_data,
    input [4:0] ex_rd_addr,
    input [31:0] ex_branch_target,
    input ex_branch_taken,
    input ex_mem_write,
    input ex_mem_read,
    input [1:0] ex_wb_sel,
    input ex_reg_write,
    input [2:0] ex_funct3,
    input [31:0] ex_pc_plus4,
    input [31:0] mem_alu_result,
    input [31:0] mem_load_data,
    input [4:0] mem_rd_addr,
    input mem_reg_write,
    input [1:0] mem_wb_sel,
    input [31:0] mem_pc_plus4,
    output reg [31:0] if_id_pc,
    output reg [31:0] if_id_instr,
    output reg [31:0] id_ex_rs1_data,
    output reg [31:0] id_ex_rs2_data,
    output reg [4:0] id_ex_rs1_addr,
    output reg [4:0] id_ex_rs2_addr,
    output reg [4:0] id_ex_rd_addr,
    output reg [31:0] id_ex_imm,
    output reg [3:0] id_ex_alu_op,
    output reg id_ex_alu_src,
    output reg id_ex_mem_write,
    output reg id_ex_mem_read,
    output reg [1:0] id_ex_wb_sel,
    output reg id_ex_reg_write,
    output reg id_ex_branch,
    output reg id_ex_jump,
    output reg [2:0] id_ex_branch_funct3,
    output reg id_ex_is_auipc,
    output reg [31:0] id_ex_pc_plus4,
    output reg [31:0] ex_mem_alu_result,
    output reg [31:0] ex_mem_rs2_data,
    output reg [4:0] ex_mem_rd_addr,
    output reg [31:0] ex_mem_branch_target,
    output reg ex_mem_branch_taken,
    output reg ex_mem_mem_write,
    output reg ex_mem_mem_read,
    output reg [1:0] ex_mem_wb_sel,
    output reg ex_mem_reg_write,
    output reg [2:0] ex_mem_funct3,
    output reg [31:0] ex_mem_pc_plus4,
    output reg [31:0] mem_wb_alu_result,
    output reg [31:0] mem_wb_load_data,
    output reg [4:0] mem_wb_rd_addr,
    output reg mem_wb_reg_write,
    output reg [1:0] mem_wb_wb_sel,
    output reg [31:0] mem_wb_pc_plus4
);

always @(posedge clk) begin
    if (rst) begin
        if_id_pc <= 32'b0;
        if_id_instr <= 32'b0;
    end else if (!stall_if_id) begin
        if (flush_if_id) begin
            if_id_instr <= 32'h00000013; // NOP
        end else begin
            if_id_pc <= if_pc;
            if_id_instr <= if_instr;
        end
    end

    if (stall_id_ex) begin
        // Hold current values
    end else if (flush_id_ex) begin
        id_ex_rs1_data <= 32'b0;
        id_ex_rs2_data <= 32'b0;
        id_ex_rs1_addr <= 5'b0;
        id_ex_rs2_addr <= 5'b0;
        id_ex_rd_addr <= 5'b0;
        id_ex_imm <= 32'b0;
        id_ex_alu_op <= 4'b0;
        id_ex_alu_src <= 1'b0;
        id_ex_mem_write <= 1'b0;
        id_ex_mem_read <= 1'b0;
        id_ex_wb_sel <= 2'b0;
        id_ex_reg_write <= 1'b0;
        id_ex_branch <= 1'b0;
        id_ex_jump <= 1'b0;
        id_ex_branch_funct3 <= 3'b0;
        id_ex_is_auipc <= 1'b0;
        id_ex_pc_plus4 <= 32'b0;
    end else begin
        id_ex_rs1_data <= id_rs1_data;
        id_ex_rs2_data <= id_rs2_data;
        id_ex_rs1_addr <= id_rs1_addr;
        id_ex_rs2_addr <= id_rs2_addr;
        id_ex_rd_addr <= id_rd_addr;
        id_ex_imm <= id_imm;
        id_ex_alu_op <= id_alu_op;
        id_ex_alu_src <= id_alu_src;
        id_ex_mem_write <= id_mem_write;
        id_ex_mem_read <= id_mem_read;
        id_ex_wb_sel <= id_wb_sel;
        id_ex_reg_write <= id_reg_write;
        id_ex_branch <= id_branch;
        id_ex_jump <= id_jump;
        id_ex_branch_funct3 <= id_branch_funct3;
        id_ex_is_auipc <= id_is_auipc;
        id_ex_pc_plus4 <= id_pc_plus4;
    end
end

always @(posedge clk) begin
    if (rst) begin
        ex_mem_alu_result <= 32'b0;
        ex_mem_rs2_data <= 32'b0;
        ex_mem_rd_addr <= 5'b0;
        ex_mem_branch_target <= 32'b0;
        ex_mem_branch_taken <= 1'b0;
        ex_mem_mem_write <= 1'b0;
        ex_mem_mem_read <= 1'b0;
        ex_mem_wb_sel <= 2'b0;
        ex_mem_reg_write <= 1'b0;
        ex_mem_funct3 <= 3'b0;
        ex_mem_pc_plus4 <= 32'b0;
    end else if (flush_ex_mem) begin
        // Flush logic can be added here if needed
    end else begin
        ex_mem_alu_result <= ex_alu_result;
        ex_mem_rs2_data <= ex_rs2_data;
        ex_mem_rd_addr <= ex_rd_addr;
        ex_mem_branch_target <= ex_branch_target;
        ex_mem_branch_taken <= ex_branch_taken;
        ex_mem_mem_write <= ex_mem_write;
        ex_mem_mem_read <= ex_mem_read;
        ex_mem_wb_sel <= ex_wb_sel;
        ex_mem_reg_write <= ex_reg_write;
        ex_mem_funct3 <= ex_funct3;
        ex_mem_pc_plus4 <= ex_pc_plus4;
    end
end

always @(posedge clk) begin
    if (rst) begin
        mem_wb_alu_result <= 32'b0;
        mem_wb_load_data <= 32'b0;
        mem_wb_rd_addr <= 5'b0;
        mem_wb_reg_write <= 1'b0;
        mem_wb_wb_sel <= 2'b0;
        mem_wb_pc_plus4 <= 32'b0;
    end else begin
        mem_wb_alu_result <= mem_alu_result;
        mem_wb_load_data <= mem_load_data;
        mem_wb_rd_addr <= mem_rd_addr;
        mem_wb_reg_write <= mem_reg_write;
        mem_wb_wb_sel <= mem_wb_sel;
        mem_wb_pc_plus4 <= mem_pc_plus4;
    end
end

endmodule
