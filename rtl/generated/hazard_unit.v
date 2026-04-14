module hazard_unit(
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

  always @(*) begin
    // Default values
    pc_write = 1'b1;
    if_id_write = 1'b1;
    id_ex_flush = 1'b0;
    if_id_flush = 1'b0;
    forward_a = 2'b00;
    forward_b = 2'b00;

    // Load-use hazard detection
    if (id_ex_mem_read && id_ex_rd != 5'b0 && 
        (id_ex_rd == if_id_rs1 || id_ex_rd == if_id_rs2)) begin
      pc_write = 1'b0;       // Stall PC
      if_id_write = 1'b0;    // Stall IF/ID register
      id_ex_flush = 1'b1;    // Insert bubble in ID/EX
    end

    // Branch flush
    if (branch_taken_ex) begin
      if_id_flush = 1'b1;    // Flush IF/ID register
      id_ex_flush = 1'b1;     // Flush ID/EX register
    end

    // Forwarding logic
    if (ex_mem_reg_write && ex_mem_rd != 5'b0) begin
      if (ex_mem_rd == id_ex_rs1) begin
        forward_a = 2'b01;    // Forward from EX/MEM
      end
      if (ex_mem_rd == id_ex_rs2) begin
        forward_b = 2'b01;    // Forward from EX/MEM
      end
    end

    if (mem_wb_reg_write && mem_wb_rd != 5'b0) begin
      if (mem_wb_rd == id_ex_rs1 && !(ex_mem_reg_write && ex_mem_rd == id_ex_rs1)) begin
        forward_a = 2'b10;    // Forward from MEM/WB
      end
      if (mem_wb_rd == id_ex_rs2 && !(ex_mem_reg_write && ex_mem_rd == id_ex_rs2)) begin
        forward_b = 2'b10;    // Forward from MEM/WB
      end
    end
  end

endmodule
