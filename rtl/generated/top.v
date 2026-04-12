module top (
    input wire clk,
    input wire rst
);

    // =========================================================================
    // Opcode constants
    // =========================================================================
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

    // ALU ops
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

    // WB sel
    localparam WB_ALU  = 2'b00;
    localparam WB_MEM  = 2'b01;
    localparam WB_PC4  = 2'b10;
    localparam WB_CSR  = 2'b11;

    // =========================================================================
    // Unified memory
    // =========================================================================
    reg [31:0] mem [0:65535];
    initial $readmemh("mem_init.hex", mem);

    // =========================================================================
    // PC register
    // =========================================================================
    reg [31:0] pc;

    // =========================================================================
    // IF/ID pipeline register
    // =========================================================================
    reg [31:0] if_id_pc;
    reg [31:0] if_id_instr;

    // =========================================================================
    // ID/EX pipeline register
    // =========================================================================
    reg [31:0] id_ex_pc;
    reg [31:0] id_ex_rs1_data;
    reg [31:0] id_ex_rs2_data;
    reg [4:0]  id_ex_rs1_addr;
    reg [4:0]  id_ex_rs2_addr;
    reg [4:0]  id_ex_rd_addr;
    reg [31:0] id_ex_imm;
    reg [3:0]  id_ex_alu_op;
    reg        id_ex_alu_src;
    reg        id_ex_mem_write;
    reg        id_ex_mem_read;
    reg [1:0]  id_ex_wb_sel;
    reg        id_ex_reg_write;
    reg        id_ex_branch;
    reg        id_ex_jump;
    reg [2:0]  id_ex_branch_funct3;
    reg        id_ex_is_auipc;
    reg [31:0] id_ex_pc_plus4;

    // =========================================================================
    // EX/MEM pipeline register
    // =========================================================================
    reg [31:0] ex_mem_alu_result;
    reg [31:0] ex_mem_rs2_data;
    reg [4:0]  ex_mem_rd_addr;
    reg [31:0] ex_mem_branch_target;
    reg        ex_mem_branch_taken;
    reg        ex_mem_mem_write;
    reg        ex_mem_mem_read;
    reg [1:0]  ex_mem_wb_sel;
    reg        ex_mem_reg_write;
    reg [31:0] ex_mem_pc_plus4;
    reg [2:0]  ex_mem_funct3;

    // =========================================================================
    // MEM/WB pipeline register
    // =========================================================================
    reg [31:0] mem_wb_alu_result;
    reg [31:0] mem_wb_load_data;
    reg [4:0]  mem_wb_rd_addr;
    reg        mem_wb_reg_write;
    reg [1:0]  mem_wb_wb_sel;
    reg [31:0] mem_wb_pc_plus4;

    // =========================================================================
    // Fetch
    // =========================================================================
    wire [31:0] instr_fetch = mem[pc >> 2];

    // =========================================================================
    // Decoder wires
    // =========================================================================
    wire [6:0]  dec_opcode;
    wire [4:0]  dec_rs1_addr, dec_rs2_addr, dec_rd_addr;
    wire [2:0]  dec_funct3;
    wire [6:0]  dec_funct7;
    wire [31:0] dec_imm;
    wire [3:0]  dec_alu_op;
    wire        dec_alu_src;
    wire        dec_mem_write;
    wire        dec_mem_read;
    wire [1:0]  dec_wb_sel;
    wire        dec_reg_write;
    wire        dec_branch;
    wire        dec_jump;
    wire        dec_is_auipc;

    // =========================================================================
    // Regfile wires
    // =========================================================================
    wire [31:0] rf_rs1_data, rf_rs2_data;

    // =========================================================================
    // Hazard unit wires
    // =========================================================================
    wire load_stall;
    wire [1:0] forward_a, forward_b;

    // =========================================================================
    // Forwarded operands
    // =========================================================================
    // Writeback value (for forwarding from MEM/WB)
    reg [31:0] wb_data;
    always @(*) begin
        case (mem_wb_wb_sel)
            WB_ALU: wb_data = mem_wb_alu_result;
            WB_MEM: wb_data = mem_wb_load_data;
            WB_PC4: wb_data = mem_wb_pc_plus4;
            WB_CSR: wb_data = 32'b0; // CSR stub
            default: wb_data = mem_wb_alu_result;
        endcase
    end

    wire [31:0] forwarded_rs1, forwarded_rs2;
    assign forwarded_rs1 = (forward_a == 2'b10) ? ex_mem_alu_result :
                           (forward_a == 2'b01) ? wb_data :
                           id_ex_rs1_data;

    assign forwarded_rs2 = (forward_b == 2'b10) ? ex_mem_alu_result :
                           (forward_b == 2'b01) ? wb_data :
                           id_ex_rs2_data;

    // =========================================================================
    // ALU wires
    // =========================================================================
    wire [31:0] alu_result;
    wire        alu_zero;

    // ALU operand A mux
    wire ex_is_auipc = id_ex_is_auipc;
    wire ex_branch   = id_ex_branch;
    wire ex_jump     = id_ex_jump;
    wire [31:0] ex_pc = id_ex_pc;

    wire [31:0] alu_a = (ex_is_auipc | ex_branch | ex_jump) ? ex_pc : forwarded_rs1;
    wire [31:0] alu_b = id_ex_alu_src ? id_ex_imm : forwarded_rs2;

    // =========================================================================
    // Branch unit wires
    // =========================================================================
    wire        branch_taken_ex;
    wire [31:0] branch_target_ex;

    // Jump target for JAL/JALR (computed in EX)
    // For JAL: PC + imm, for JALR: rs1 + imm
    // branch_target_ex from branch_unit covers branches; jump target is alu_result for JALR
    // We'll use alu_result as jump_target when jump is set
    wire [31:0] jump_target = alu_result; // For JAL: pc+imm (alu_a=pc, alu_b=imm), JALR: rs1+imm

    // =========================================================================
    // LSU wires
    // =========================================================================
    wire [31:0] load_data;
    wire [3:0]  mem_byte_en;
    wire [31:0] mem_write_data;
    wire [31:0] mem_addr;

    // =========================================================================
    // CSR wires
    // =========================================================================
    wire [31:0] csr_rdata;

    // =========================================================================
    // Submodule instantiations
    // =========================================================================

    decoder dec_inst (
        .instr        (if_id_instr),
        .opcode       (dec_opcode),
        .rs1_addr     (dec_rs1_addr),
        .rs2_addr     (dec_rs2_addr),
        .rd_addr      (dec_rd_addr),
        .funct3       (dec_funct3),
        .funct7       (dec_funct7),
        .imm          (dec_imm),
        .alu_op       (dec_alu_op),
        .alu_src      (dec_alu_src),
        .mem_write    (dec_mem_write),
        .mem_read     (dec_mem_read),
        .wb_sel       (dec_wb_sel),
        .reg_write    (dec_reg_write),
        .branch       (dec_branch),
        .jump         (dec_jump),
        .is_auipc     (dec_is_auipc)
    );

    regfile rf_inst (
        .clk      (clk),
        .rs1_addr (dec_rs1_addr),
        .rs2_addr (dec_rs2_addr),
        .rd_addr  (mem_wb_rd_addr),
        .rd_data  (wb_data),
        .reg_write(mem_wb_reg_write),
        .rs1_data (rf_rs1_data),
        .rs2_data (rf_rs2_data)
    );

    alu alu_inst (
        .a        (alu_a),
        .b        (alu_b),
        .alu_op   (id_ex_alu_op),
        .result   (alu_result),
        .zero     (alu_zero)
    );

    branch_unit bu_inst (
        .pc           (id_ex_pc),
        .rs1          (forwarded_rs1),
        .imm          (id_ex_imm),
        .funct3       (id_ex_branch_funct3),
        .branch       (id_ex_branch),
        .jump         (id_ex_jump),
        .alu_result   (alu_result),
        .branch_taken (branch_taken_ex),
        .branch_target(branch_target_ex)
    );

    lsu lsu_inst (
        .funct3       (ex_mem_funct3),
        .mem_addr     (ex_mem_alu_result),
        .rs2_data     (ex_mem_rs2_data),
        .mem_read     (ex_mem_mem_read),
        .mem_write    (ex_mem_mem_write),
        .mem_rdata    (mem[ex_mem_alu_result[17:2]]),
        .load_data    (load_data),
        .byte_en      (mem_byte_en),
        .write_data   (mem_write_data),
        .mem_addr_out (mem_addr)
    );

    csr_unit csr_inst (
        .clk      (clk),
        .rst      (rst),
        .instr    (if_id_instr),
        .rs1_data (rf_rs1_data),
        .csr_rdata(csr_rdata)
    );

    hazard_unit hu_inst (
        .id_ex_mem_read  (id_ex_mem_read),
        .id_ex_rd_addr   (id_ex_rd_addr),
        .if_id_rs1_addr  (dec_rs1_addr),
        .if_id_rs2_addr  (dec_rs2_addr),
        .ex_mem_rd_addr  (ex_mem_rd_addr),
        .ex_mem_reg_write(ex_mem_reg_write),
        .mem_wb_rd_addr  (mem_wb_rd_addr),
        .mem_wb_reg_write(mem_wb_reg_write),
        .id_ex_rs1_addr  (id_ex_rs1_addr),
        .id_ex_rs2_addr  (id_ex_rs2_addr),
        .load_stall      (load_stall),
        .forward_a       (forward_a),
        .forward_b       (forward_b)
    );

    pipeline_regs pr_inst (
        .clk (clk),
        .rst (rst)
    );

    // =========================================================================
    // PC update
    // =========================================================================
    always @(posedge clk) begin
        if (rst)
            pc <= 32'h0;
        else if (branch_taken_ex)
            pc <= branch_target_ex;
        else if (id_ex_jump && !load_stall)
            pc <= jump_target;
        else if (load_stall)
            pc <= pc;
        else
            pc <= pc + 4;
    end

    // =========================================================================
    // IF/ID register
    // =========================================================================
    always @(posedge clk) begin
        if (rst) begin
            if_id_pc    <= 32'b0;
            if_id_instr <= 32'h00000013; // NOP
        end else if (branch_taken_ex) begin
            // Flush
            if_id_pc    <= 32'b0;
            if_id_instr <= 32'h00000013;
        end else if (load_stall) begin
            // Hold
            if_id_pc    <= if_id_pc;
            if_id_instr <= if_id_instr;
        end else begin
            if_id_pc    <= pc;
            if_id_instr <= instr_fetch;
        end
    end

    // =========================================================================
    // ID/EX register
    // =========================================================================
    wire [31:0] if_id_pc_plus4 = if_id_pc + 4;

    always @(posedge clk) begin
        if (rst || branch_taken_ex || load_stall) begin
            id_ex_pc           <= 32'b0;
            id_ex_rs1_data     <= 32'b0;
            id_ex_rs2_data     <= 32'b0;
            id_ex_rs1_addr     <= 5'b0;
            id_ex_rs2_addr     <= 5'b0;
            id_ex_rd_addr      <= 5'b0;
            id_ex_imm          <= 32'b0;
            id_ex_alu_op       <= 4'b0;
            id_ex_alu_src      <= 1'b0;
            id_ex_mem_write    <= 1'b0;
            id_ex_mem_read     <= 1'b0;
            id_ex_wb_sel       <= 2'b0;
            id_ex_reg_write    <= 1'b0;
            id_ex_branch       <= 1'b0;
            id_ex_jump         <= 1'b0;
            id_ex_branch_funct3<= 3'b0;
            id_ex_is_auipc     <= 1'b0;
            id_ex_pc_plus4     <= 32'b0;
        end else begin
            id_ex_pc           <= if_id_pc;
            id_ex_rs1_data     <= rf_rs1_data;
            id_ex_rs2_data     <= rf_rs2_data;
            id_ex_rs1_addr     <= dec_rs1_addr;
            id_ex_rs2_addr     <= dec_rs2_addr;
            id_ex_rd_addr      <= dec_rd_addr;
            id_ex_imm          <= dec_imm;
            id_ex_alu_op       <= dec_alu_op;
            id_ex_alu_src      <= dec_alu_src;
            id_ex_mem_write    <= dec_mem_write;
            id_ex_mem_read     <= dec_mem_read;
            id_ex_wb_sel       <= dec_wb_sel;
            id_ex_reg_write    <= dec_reg_write;
            id_ex_branch       <= dec_branch;
            id_ex_jump         <= dec_jump;
            id_ex_branch_funct3<= dec_funct3;
            id_ex_is_auipc     <= dec_is_auipc;
            id_ex_pc_plus4     <= if_id_pc_plus4;
        end
    end

    // =========================================================================
    // EX/MEM register
    // =========================================================================
    always @(posedge clk) begin
        if (rst) begin
            ex_mem_alu_result  <= 32'b0;
            ex_mem_rs2_data    <= 32'b0;
            ex_mem_rd_addr     <= 5'b0;
            ex_mem_branch_target <= 32'b0;
            ex_mem_branch_taken  <= 1'b0;
            ex_mem_mem_write   <= 1'b0;
            ex_mem_mem_read    <= 1'b0;
            ex_mem_wb_sel      <= 2'b0;
            ex_mem_reg_write   <= 1'b0;
            ex_mem_pc_plus4    <= 32'b0;
            ex_mem_funct3      <= 3'b0;
        end else begin
            ex_mem_alu_result  <= alu_result;
            ex_mem_rs2_data    <= forwarded_rs2;
            ex_mem_rd_addr     <= id_ex_rd_addr;
            ex_mem_branch_target <= branch_target_ex;
            ex_mem_branch_taken  <= branch_taken_ex;
            ex_mem_mem_write   <= id_ex_mem_write;
            ex_mem_mem_read    <= id_ex_mem_read;
            ex_mem_wb_sel      <= id_ex_wb_sel;
            ex_mem_reg_write   <= id_ex_reg_write;
            ex_mem_pc_plus4    <= id_ex_pc_plus4;
            ex_mem_funct3      <= id_ex_branch_funct3;
        end
    end

    // =========================================================================
    // Data memory: synchronous write, combinational read
    // =========================================================================
    always @(posedge clk) begin
        if (ex_mem_mem_write) begin
            if (mem_byte_en[0]) mem[mem_addr[17:2]][7:0]   <= mem_write_data[7:0];
            if (mem_byte_en[1]) mem[mem_addr[17:2]][15:8]  <= mem_write_data[15:8];
            if (mem_byte_en[2]) mem[mem_addr[17:2]][23:16] <= mem_write_data[23:16];
            if (mem_byte_en[3]) mem[mem_addr[17:2]][31:24] <= mem_write_data[31:24];
        end
    end

    // =========================================================================
    // MEM/WB register
    // =========================================================================
    always @(posedge clk) begin
        if (rst) begin
            mem_wb_alu_result <= 32'b0;
            mem_wb_load_data  <= 32'b0;
            mem_wb_rd_addr    <= 5'b0;
            mem_wb_reg_write  <= 1'b0;
            mem_wb_wb_sel     <= 2'b0;
            mem_wb_pc_plus4   <= 32'b0;
        end else begin
            mem_wb_alu_result <= ex_mem_alu_result;
            mem_wb_load_data  <= load_data;
            mem_wb_rd_addr    <= ex_mem_rd_addr;
            mem_wb_reg_write  <= ex_mem_reg_write;
            mem_wb_wb_sel     <= ex_mem_wb_sel;
            mem_wb_pc_plus4   <= ex_mem_pc_plus4;
        end
    end

    // =========================================================================
    // Simulation display
    // =========================================================================
    always @(posedge clk) begin
        if (!rst)
            $display("PC=%08h INSTR=%08h", if_id_pc, if_id_instr);
    end

endmodule


// =============================================================================
// Decoder
// =============================================================================
module decoder (
    input  wire [31:0] instr,
    output wire [6:0]  opcode,
    output wire [4:0]  rs1_addr,
    output wire [4:0]  rs2_addr,
    output wire [4:0]  rd_addr,
    output wire [2:0]  funct3,
    output wire [6:0]  funct7,
    output wire [31:0] imm,
    output reg  [3:0]  alu_op,
    output reg         alu_src,
    output reg         mem_write,
    output reg         mem_read,
    output reg  [1:0]  wb_sel,
    output reg         reg_write,
    output reg         branch,
    output reg         jump,
    output reg         is_auipc
);
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

    localparam ALU_ADD  = 4'b0000;
    localparam ALU_SUB  = 4'b0001;
    localparam ALU_AND  = 4'b0010;
    localparam ALU_OR   = 4'b