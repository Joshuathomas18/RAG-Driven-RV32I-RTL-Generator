module hazard_unit (
    input  [4:0] id_ex_rs1,
    input  [4:0] id_ex_rs2,
    input  [4:0] ex_mem_rd,
    input  [4:0] mem_wb_rd,
    input        ex_mem_reg_write,
    input        mem_wb_reg_write,
    input        id_ex_mem_read,
    input  [4:0] if_id_rs1,
    input  [4:0] if_id_rs2,
    input  [4:0] id_ex_rd,
    input        branch_taken_ex,
    output reg   pc_write,
    output reg   if_id_write,
    output reg   id_ex_flush,
    output reg   if_id_flush,
    output reg [1:0] forward_a,
    output reg [1:0] forward_b
);

    wire load_use_hazard;

    assign load_use_hazard = id_ex_mem_read &&
                             (id_ex_rd != 5'b0) &&
                             ((id_ex_rd == if_id_rs1) || (id_ex_rd == if_id_rs2));

    // Forwarding logic
    always @(*) begin
        // Forward A (for rs1 in EX stage)
        if (ex_mem_reg_write && (ex_mem_rd != 5'b0) && (ex_mem_rd == id_ex_rs1)) begin
            forward_a = 2'b01; // EX/MEM forwarding (highest priority)
        end else if (mem_wb_reg_write && (mem_wb_rd != 5'b0) && (mem_wb_rd == id_ex_rs1)) begin
            forward_a = 2'b10; // MEM/WB forwarding
        end else begin
            forward_a = 2'b00; // No forwarding, use register file
        end

        // Forward B (for rs2 in EX stage)
        if (ex_mem_reg_write && (ex_mem_rd != 5'b0) && (ex_mem_rd == id_ex_rs2)) begin
            forward_b = 2'b01; // EX/MEM forwarding (highest priority)
        end else if (mem_wb_reg_write && (mem_wb_rd != 5'b0) && (mem_wb_rd == id_ex_rs2)) begin
            forward_b = 2'b10; // MEM/WB forwarding
        end else begin
            forward_b = 2'b00; // No forwarding, use register file
        end
    end

    // Hazard control signals
    always @(*) begin
        if (load_use_hazard) begin
            // Stall: hold PC and IF/ID, flush ID/EX (insert bubble)
            pc_write    = 1'b0;
            if_id_write = 1'b0;
            id_ex_flush = 1'b1;
            if_id_flush = 1'b0;
        end else if (branch_taken_ex) begin
            // Branch taken: flush IF/ID and ID/EX
            pc_write    = 1'b1;
            if_id_write = 1'b1;
            id_ex_flush = 1'b1;
            if_id_flush = 1'b1;
        end else begin
            // Normal operation
            pc_write    = 1'b1;
            if_id_write = 1'b1;
            id_ex_flush = 1'b0;
            if_id_flush = 1'b0;
        end
    end

endmodule