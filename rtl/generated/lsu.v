module lsu (
    input mem_read,
    input mem_write,
    input [2:0] mem_op,    // funct3 from instruction: 000=LB/SB 001=LH/SH 010=LW/SW 100=LBU 101=LHU
    input [31:0] addr, 
    input [31:0] wdata,
    input [31:0] mem_rdata,  // raw word from memory array
    output reg [31:0] rdata, // sign/zero extended load result
    output [31:0] mem_addr,  // word-aligned address to memory
    output [31:0] mem_wdata, // formatted write data
    output [3:0]  mem_be     // byte enables for write
);

    // Word-aligned address calculation
    assign mem_addr = {addr[31:2], 2'b00};

    // Memory write data formatting
    assign mem_wdata = (mem_op[1:0] == 2'b00) ? {24'b0, wdata[7:0]} : // Byte
                       (mem_op[1:0] == 2'b01) ? {16'b0, wdata[15:0]} : // Halfword
                       wdata; // Word

    // Byte enables for store
    assign mem_be = (mem_op[1:0] == 2'b00) ? (4'b0001 << addr[1:0]) : // SB
                    (mem_op[1:0] == 2'b01) ? (addr[1] ? 4'b1100 : 4'b0011) : // SH
                    4'b1111; // SW

    // Load data processing
    always @(*) begin
        case (mem_op)
            3'b000: rdata = {{24{mem_rdata[7]}}, mem_rdata[7:0]}; // LB
            3'b001: rdata = {{16{mem_rdata[15]}}, mem_rdata[15:0]}; // LH
            3'b010: rdata = mem_rdata; // LW
            3'b100: rdata = {24'b0, mem_rdata[7:0]}; // LBU
            3'b101: rdata = {16'b0, mem_rdata[15:0]}; // LHU
            default: rdata = 32'b0; // Default case
        endcase
    end

endmodule
