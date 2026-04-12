module pipeline_regs (
    input  wire        clk,
    input  wire        rst,

    // IF/ID controls
    input  wire        stall_if_id,
    input  wire        flush_if_id,

    // IF/ID inputs
    input  wire [31:0] if_pc,
    input  wire [31:0] if_instr,

    // IF/ID outputs
    output reg  [31:0] id_pc,
    output reg  [31:0] id_instr,

    // ID/EX controls
    input  wire        stall_id_ex,
    input  wire        flush_id_ex,

    // ID/EX inputs
    input  wire [31:0] id_ex_pc,
    input  wire [31:0] id_ex_rs1_data,
    input  wire [31:0] id_ex_rs2_data,
    input  wire [4:0]  id_ex_rs1_addr,
    input  wire [4:0]  id_ex_rs2_addr,
    input  wire [4:0]  id_ex_rd_addr,
    input  wire [31:0] id_ex_imm,
    input  wire [3:0]  id_ex_alu_op,
    input  wire        id_ex_alu_src,
    input  wire        id_ex_mem_write,
    input  wire        id_ex_mem_read,
    input  wire [1:0]  id_ex_wb_sel,
    input  wire        id_ex_reg_write,
    input  wire        id_ex_branch,
    input  wire        id_ex_jump,
    input  wire [2:0]  id_ex_branch_funct3,
    input  wire        id_ex_is_auipc,
    input  wire [31:0] id_ex_pc_plus4,

    // ID/EX outputs
    output reg  [31:0] ex_pc,
    output reg  [31:0] ex_rs1_data,
    output reg  [31:0] ex_rs2_data,
    output reg  [4:0]  ex_rs1_addr,
    output reg  [4:0]  ex_rs2_addr,
    output reg  [4:0]  ex_rd_addr,
    output reg  [31:0] ex_imm,
    output reg  [3:0]  ex_alu_op,
    output reg         ex_alu_src,
    output reg         ex_mem_write,
    output reg         ex_mem_read,
    output reg  [1:0]  ex_wb_sel,
    output reg         ex_reg_write,
    output reg         ex_branch,
    output reg         ex_jump,
    output reg  [2:0]  ex_branch_funct3,
    output reg         ex_is_auipc,
    output reg  [31:0] ex_pc_plus4,

    // EX/MEM controls
    input  wire        flush_ex_mem,

    // EX/MEM inputs
    input  wire [31:0] ex_mem_alu_result,
    input  wire [31:0] ex_mem_rs2_data,
    input  wire [4:0]  ex_mem_rd_addr,
    input  wire [31:0] ex_mem_branch_target,
    input  wire        ex_mem_branch_taken,
    input  wire        ex_mem_mem_write,
    input  wire        ex_mem_mem_read,
    input  wire [1:0]  ex_mem_wb_sel,
    input  wire        ex_mem_reg_write,
    input  wire [31:0] ex_mem_pc_plus4,

    // EX/MEM outputs
    output reg  [31:0] mem_alu_result,
    output reg  [31:0] mem_rs2_data,
    output reg  [4:0]  mem_rd_addr,
    output reg  [31:0] mem_branch_target,
    output reg         mem_branch_taken,
    output reg         mem_mem_write,
    output reg         mem_mem_read,
    output reg  [1:0]  mem_wb_sel,
    output reg         mem_reg_write,
    output reg  [31:0] mem_pc_plus4,

    // MEM/WB inputs
    input  wire [31:0] mem_wb_alu_result,
    input  wire [31:0] mem_wb_load_data,
    input  wire [4:0]  mem_wb_rd_addr,
    input  wire        mem_wb_reg_write,
    input  wire [1:0]  mem_wb_wb_sel,
    input  wire [31:0] mem_wb_pc_plus4,

    // MEM/WB outputs
    output reg  [31:0] wb_alu_result,
    output reg  [31:0] wb_load_data,
    output reg  [4:0]  wb_rd_addr,
    output reg         wb_reg_write,
    output reg  [1:0]  wb_wb_sel,
    output reg  [31:0] wb_pc_plus4
);

    // IF/ID pipeline register
    always @(posedge clk) begin
        if (rst) begin
            id_pc    <= 32'h0;
            id_instr <= 32'h00000013;
        end else if (flush_if_id) begin
            id_pc    <= if_pc;
            id_instr <= 32'h00000013;
        end else if (!stall_if_id) begin
            id_pc    <= if_pc;
            id_instr <= if_instr;
        end
        // stall: hold current value (no update)
    end

    // ID/EX pipeline register
    always @(posedge clk) begin
        if (rst) begin
            ex_pc            <= 32'h0;
            ex_rs1_data      <= 32'h0;
            ex_rs2_data      <= 32'h0;
            ex_rs1_addr      <= 5'h0;
            ex_rs2_addr      <= 5'h0;
            ex_rd_addr       <= 5'h0;
            ex_imm           <= 32'h0;
            ex_alu_op        <= 4'h0;
            ex_alu_src       <= 1'b0;
            ex_mem_write     <= 1'b0;
            ex_mem_read      <= 1'b0;
            ex_wb_sel        <= 2'b00;
            ex_reg_write     <= 1'b0;
            ex_branch        <= 1'b0;
            ex_jump          <= 1'b0;
            ex_branch_funct3 <= 3'h0;
            ex_is_auipc      <= 1'b0;
            ex_pc_plus4      <= 32'h0;
        end else if (flush_id_ex) begin
            // Keep data fields, clear control signals
            ex_pc            <= id_ex_pc;
            ex_rs1_data      <= id_ex_rs1_data;
            ex_rs2_data      <= id_ex_rs2_data;
            ex_rs1_addr      <= id_ex_rs1_addr;
            ex_rs2_addr      <= id_ex_rs2_addr;
            ex_rd_addr       <= id_ex_rd_addr;
            ex_imm           <= id_ex_imm;
            ex_alu_op        <= id_ex_alu_op;
            ex_alu_src       <= id_ex_alu_src;
            ex_mem_write     <= 1'b0;
            ex_mem_read      <= 1'b0;
            ex_wb_sel        <= 2'b00;
            ex_reg_write     <= 1'b0;
            ex_branch        <= 1'b0;
            ex_jump          <= 1'b0;
            ex_branch_funct3 <= id_ex_branch_funct3;
            ex_is_auipc      <= 1'b0;
            ex_pc_plus4      <= id_ex_pc_plus4;
        end else if (!stall_id_ex) begin
            ex_pc            <= id_ex_pc;
            ex_rs1_data      <= id_ex_rs1_data;
            ex_rs2_data      <= id_ex_rs2_data;
            ex_rs1_addr      <= id_ex_rs1_addr;
            ex_rs2_addr      <= id_ex_rs2_addr;
            ex_rd_addr       <= id_ex_rd_addr;
            ex_imm           <= id_ex_imm;
            ex_alu_op        <= id_ex_alu_op;
            ex_alu_src       <= id_ex_alu_src;
            ex_mem_write     <= id_ex_mem_write;
            ex_mem_read      <= id_ex_mem_read;
            ex_wb_sel        <= id_ex_wb_sel;
            ex_reg_write     <= id_ex_reg_write;
            ex_branch        <= id_ex_branch;
            ex_jump          <= id_ex_jump;
            ex_branch_funct3 <= id_ex_branch_funct3;
            ex_is_auipc      <= id_ex_is_auipc;
            ex_pc_plus4      <= id_ex_pc_plus4;
        end
        // stall: hold current value (no update)
    end

    // EX/MEM pipeline register
    always @(posedge clk) begin
        if (rst) begin
            mem_alu_result    <= 32'h0;
            mem_rs2_data      <= 32'h0;
            mem_rd_addr       <= 5'h0;
            mem_branch_target <= 32'h0;
            mem_branch_taken  <= 1'b0;
            mem_mem_write     <= 1'b0;
            mem_mem_read      <= 1'b0;
            mem_wb_sel        <= 2'b00;
            mem_reg_write     <= 1'b0;
            mem_pc_plus4      <= 32'h0;
        end else if (flush_ex_mem) begin
            mem_alu_result    <= 32'h0;
            mem_rs2_data      <= 32'h0;
            mem_rd_addr       <= 5'h0;
            mem_branch_target <= 32'h0;
            mem_branch_taken  <= 1'b0;
            mem_mem_write     <= 1'b0;
            mem_mem_read      <= 1'b0;
            mem_wb_sel        <= 2'b00;
            mem_reg_write     <= 1'b0;
            mem_pc_plus4      <= 32'h0;
        end else begin
            mem_alu_result    <= ex_mem_alu_result;
            mem_rs2_data      <= ex_mem_rs2_data;
            mem_rd_addr       <= ex_mem_rd_addr;
            mem_branch_target <= ex_mem_branch_target;
            mem_branch_taken  <= ex_mem_branch_taken;
            mem_mem_write     <= ex_mem_mem_write;
            mem_mem_read      <= ex_mem_mem_read;
            mem_wb_sel        <= ex_mem_wb_sel;
            mem_reg_write     <= ex_mem_reg_write;
            mem_pc_plus4      <= ex_mem_pc_plus4;
        end
    end

    // MEM/WB pipeline register - ALL fields in ONE always block
    always @(posedge clk) begin
        if (rst) begin
            wb_alu_result <= 32'h0;
            wb_load_data  <= 32'h0;
            wb_rd_addr    <= 5'h0;
            wb_reg_write  <= 1'b0;
            wb_wb_sel     <= 2'b00;
            wb_pc_plus4   <= 32'h0;
        end else begin
            wb_alu_result <= mem_wb_alu_result;
            wb_load_data  <= mem_wb_load_data;
            wb_rd_addr    <= mem_wb_rd_addr;
            wb_reg_write  <= mem_wb_reg_write;
            wb_wb_sel     <= mem_wb_wb_sel;
            wb_pc_plus4   <= mem_wb_pc_plus4;
        end
    end

endmodule