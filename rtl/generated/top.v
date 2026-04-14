/* verilator lint_off UNUSEDSIGNAL */
/* verilator lint_off IMPLICIT */
/* verilator lint_off WIDTHEXPAND */
module top (
    input clk,
    input rst
);

    // Memory declaration
    reg [31:0] mem [0:65535]; // 256KB memory

    // PC register
    reg [31:0] pc;
    
    // Wires for pipeline registers
    wire [31:0] if_id_pc, if_id_instr;
    wire [31:0] id_ex_pc, id_ex_rs1_data, id_ex_rs2_data, id_ex_imm, id_ex_pc_plus4;
    wire [4:0] id_ex_rs1_addr, id_ex_rs2_addr, id_ex_rd_addr;
    wire [1:0] id_ex_wb_sel;
    wire id_ex_alu_src, id_ex_mem_write, id_ex_mem_read, id_ex_reg_write, id_ex_branch, id_ex_jump, id_ex_is_auipc;
    wire [2:0] id_ex_branch_funct3;
    wire [3:0] id_ex_alu_op;
    
    wire [31:0] ex_mem_alu_result, ex_mem_rs2_data, ex_mem_branch_target, ex_mem_pc_plus4;
    wire [4:0] ex_mem_rd_addr;
    wire ex_mem_branch_taken, ex_mem_mem_write, ex_mem_mem_read, ex_mem_reg_write;
    wire [1:0] ex_mem_wb_sel;
    wire [2:0] ex_mem_funct3;
    
    wire [31:0] mem_wb_alu_result, mem_wb_load_data, mem_wb_pc_plus4;
    wire [4:0] mem_wb_rd_addr;
    wire mem_wb_reg_write;
    wire [1:0] mem_wb_wb_sel;

    // Instantiate submodules
    wire [4:0] rs1, rs2, rd;
    wire [31:0] imm, csr_wdata, csr_rdata;
    wire [3:0] alu_op;
    wire alu_src, mem_read, mem_write, reg_write, branch, jump, is_auipc, csr_en;
    wire [1:0] wb_sel;
    wire [2:0] branch_funct3, funct3, csr_op;
    wire [11:0] csr_addr;
    wire [31:0] branch_target_ex; 
    wire branch_taken_ex;

    wire pc_write, if_id_write, id_ex_flush, if_id_flush;

    // PC update logic
    always @(posedge clk) begin
        if (rst) 
            pc <= 32'h0;
        else if (branch_taken_ex) 
            pc <= branch_target_ex;   // branch/JAL/JALR
        else if (!pc_write) 
            pc <= pc;                 // stall
        else 
            pc <= pc + 4;
    end

    // Instruction fetch
    wire [31:0] instr_fetch = mem[pc[17:2]];
    
    wire [31:0] rdata1, rdata2;
    wire [31:0] alu_a, alu_b, alu_result;
    wire zero;

    wire [1:0] forward_a, forward_b;

    wire [31:0] load_data, mem_addr, mem_wdata;
    wire [3:0] mem_be;
    wire [1:0] mem_size;
    wire ecall;

    // Register File write data and Forwarding logic
    wire [31:0] regfile_wdata = (mem_wb_wb_sel == 2'b00) ? mem_wb_alu_result : 
                                (mem_wb_wb_sel == 2'b01) ? mem_wb_load_data : 
                                (mem_wb_wb_sel == 2'b10) ? mem_wb_pc_plus4 : 
                                csr_rdata;

    wire [31:0] forward_a_val = (forward_a == 2'b01) ? ex_mem_alu_result :
                                (forward_a == 2'b10) ? regfile_wdata : id_ex_rs1_data;

    wire [31:0] forward_b_val = (forward_b == 2'b01) ? ex_mem_alu_result :
                                (forward_b == 2'b10) ? regfile_wdata : id_ex_rs2_data;

    assign alu_a = id_ex_is_auipc ? id_ex_pc : forward_a_val;
    assign alu_b = id_ex_alu_src ? id_ex_imm : forward_b_val;

    // Instantiate ALU
    alu alu_inst (
        .a(alu_a),
        .b(alu_b),
        .alu_op(id_ex_alu_op),
        .result(alu_result),
        .zero(zero)
    );

    // Instantiate Register File
    regfile regfile_inst (
        .clk(clk),
        .rs1(rs1),
        .rs2(rs2),
        .rd(mem_wb_rd_addr),
        .wdata(regfile_wdata),
        .we(mem_wb_reg_write),
        .rdata1(rdata1),
        .rdata2(rdata2)
    );

    // Instantiate Decoder
    decoder decoder_inst (
        .instr(if_id_instr),
        .rs1(rs1),
        .rs2(rs2),
        .rd(rd),
        .imm(imm),
        .alu_op(alu_op),
        .alu_src(alu_src),
        .mem_read(mem_read),
        .mem_write(mem_write),
        .mem_size(mem_size),
        .reg_write(reg_write),
        .wb_sel(wb_sel),
        .branch(branch),
        .jump(jump),
        .is_auipc(is_auipc),
        .branch_funct3(branch_funct3),
        .funct3(funct3),
        .csr_en(csr_en),
        .csr_addr(csr_addr),
        .csr_op(csr_op),
        .csr_wdata(csr_wdata)
    );

    // Instantiate Branch Unit
    branch_unit branch_unit_inst (
        .pc(id_ex_pc),
        .rs1(forward_a_val),
        .rs2(forward_b_val),
        .imm(id_ex_imm),
        .funct3(id_ex_branch_funct3),
        .is_branch(id_ex_branch),
        .is_jal(id_ex_jump && !id_ex_alu_src),
        .is_jalr(id_ex_jump && id_ex_alu_src),
        .branch_target(branch_target_ex),
        .branch_taken(branch_taken_ex)
    );

    // Instantiate CSR Unit
    csr_unit csr_unit_inst (
        .clk(clk),
        .rst(rst),
        .csr_we(csr_en),
        .csr_addr(csr_addr),
        .wdata(csr_wdata),
        .funct3(csr_op),
        .rdata(csr_rdata),
        .ecall(ecall)
    );

    // Instantiate Hazard Unit
    hazard_unit hazard_unit_inst (
        .id_ex_rs1(id_ex_rs1_addr),
        .id_ex_rs2(id_ex_rs2_addr),
        .ex_mem_rd(ex_mem_rd_addr),
        .mem_wb_rd(mem_wb_rd_addr),
        .ex_mem_reg_write(ex_mem_reg_write),
        .mem_wb_reg_write(mem_wb_reg_write),
        .id_ex_mem_read(id_ex_mem_read),
        .if_id_rs1(rs1),
        .if_id_rs2(rs2),
        .id_ex_rd(id_ex_rd_addr),
        .branch_taken_ex(branch_taken_ex),
        .pc_write(pc_write),
        .if_id_write(if_id_write),
        .id_ex_flush(id_ex_flush),
        .if_id_flush(if_id_flush),
        .forward_a(forward_a),
        .forward_b(forward_b)
    );

    // Memory Data Read
    wire [31:0] raw_mem_rdata = mem[mem_addr[17:2]];

    // Instantiate LSU
    lsu lsu_inst (
        .mem_read(ex_mem_mem_read),
        .mem_write(ex_mem_mem_write),
        .mem_op(ex_mem_funct3),
        .addr(ex_mem_alu_result),
        .wdata(ex_mem_rs2_data),
        .mem_rdata(raw_mem_rdata),
        .rdata(load_data),
        .mem_addr(mem_addr),
        .mem_wdata(mem_wdata),
        .mem_be(mem_be)
    );

    // Memory Data Write
    always @(posedge clk) begin
        if (ex_mem_mem_write) begin
            if (mem_be[0]) mem[mem_addr[17:2]][7:0]   <= mem_wdata[7:0];
            if (mem_be[1]) mem[mem_addr[17:2]][15:8]  <= mem_wdata[15:8];
            if (mem_be[2]) mem[mem_addr[17:2]][23:16] <= mem_wdata[23:16];
            if (mem_be[3]) mem[mem_addr[17:2]][31:24] <= mem_wdata[31:24];
        end
    end

    // Instantiate Pipeline Registers
    pipeline_regs pipeline_regs_inst (
        .clk(clk),
        .rst(rst),
        .stall_if_id(!if_id_write),
        .flush_if_id(if_id_flush),
        .stall_id_ex(1'b0),
        .flush_id_ex(id_ex_flush),
        .flush_ex_mem(1'b0),
        .if_pc(pc),
        .if_instr(instr_fetch),
        .id_rs1_data(rdata1),
        .id_rs2_data(rdata2),
        .id_rs1_addr(rs1),
        .id_rs2_addr(rs2),
        .id_rd_addr(rd),
        .id_imm(imm),
        .id_alu_op(alu_op),
        .id_alu_src(alu_src),
        .id_mem_write(mem_write),
        .id_mem_read(mem_read),
        .id_wb_sel(wb_sel),
        .id_reg_write(reg_write),
        .id_branch(branch),
        .id_jump(jump),
        .id_branch_funct3(branch_funct3),
        .id_is_auipc(is_auipc),
        .id_pc_plus4(pc + 4),
        .ex_alu_result(alu_result),
        .ex_rs2_data(forward_b_val),
        .ex_rd_addr(id_ex_rd_addr),
        .ex_branch_target(branch_target_ex),
        .ex_branch_taken(branch_taken_ex),
        .ex_mem_write(id_ex_mem_write),
        .ex_mem_read(id_ex_mem_read),
        .ex_wb_sel(id_ex_wb_sel),
        .ex_reg_write(id_ex_reg_write),
        .ex_funct3(id_ex_branch_funct3),
        .ex_pc_plus4(id_ex_pc_plus4),
        .mem_alu_result(ex_mem_alu_result),
        .mem_load_data(load_data),
        .mem_rd_addr(ex_mem_rd_addr),
        .mem_reg_write(ex_mem_reg_write),
        .mem_wb_sel(ex_mem_wb_sel),
        .mem_pc_plus4(ex_mem_pc_plus4),
        .if_id_pc(if_id_pc),
        .if_id_instr(if_id_instr),
        .id_ex_pc(id_ex_pc),
        .id_ex_rs1_data(id_ex_rs1_data),
        .id_ex_rs2_data(id_ex_rs2_data),
        .id_ex_rs1_addr(id_ex_rs1_addr),
        .id_ex_rs2_addr(id_ex_rs2_addr),
        .id_ex_rd_addr(id_ex_rd_addr),
        .id_ex_imm(id_ex_imm),
        .id_ex_alu_op(id_ex_alu_op),
        .id_ex_alu_src(id_ex_alu_src),
        .id_ex_mem_write(id_ex_mem_write),
        .id_ex_mem_read(id_ex_mem_read),
        .id_ex_wb_sel(id_ex_wb_sel),
        .id_ex_reg_write(id_ex_reg_write),
        .id_ex_branch(id_ex_branch),
        .id_ex_jump(id_ex_jump),
        .id_ex_branch_funct3(id_ex_branch_funct3),
        .id_ex_is_auipc(id_ex_is_auipc),
        .id_ex_pc_plus4(id_ex_pc_plus4),
        .ex_mem_alu_result(ex_mem_alu_result),
        .ex_mem_rs2_data(ex_mem_rs2_data),
        .ex_mem_rd_addr(ex_mem_rd_addr),
        .ex_mem_branch_target(ex_mem_branch_target),
        .ex_mem_branch_taken(ex_mem_branch_taken),
        .ex_mem_mem_write(ex_mem_mem_write),
        .ex_mem_mem_read(ex_mem_mem_read),
        .ex_mem_wb_sel(ex_mem_wb_sel),
        .ex_mem_reg_write(ex_mem_reg_write),
        .ex_mem_funct3(ex_mem_funct3),
        .ex_mem_pc_plus4(ex_mem_pc_plus4),
        .mem_wb_alu_result(mem_wb_alu_result),
        .mem_wb_load_data(mem_wb_load_data),
        .mem_wb_rd_addr(mem_wb_rd_addr),
        .mem_wb_reg_write(mem_wb_reg_write),
        .mem_wb_wb_sel(mem_wb_wb_sel),
        .mem_wb_pc_plus4(mem_wb_pc_plus4)
    );

    // Simulation display for pass detection
    always @(posedge clk) begin
        if (!rst) begin
            $display("PC=%08h INSTR=%08h", if_id_pc, if_id_instr);
            if (pc < 32)
                $display("DEBUG rst=%d pc=%08x pc_w=%d b_taken=%d b_tgt=%08x id_ex_jump=%d id_ex_alu_src=%d id_ex_branch=%d instr_fetch=%08x st_if=%d st_id=%d if_id_instr=%08x id_ex_mem_read=%d",
                         rst, pc, pc_write, branch_taken_ex, branch_target_ex, id_ex_jump, id_ex_alu_src, id_ex_branch, instr_fetch, !if_id_write, !id_ex_flush, if_id_instr, id_ex_mem_read);
        end
    end

endmodule
