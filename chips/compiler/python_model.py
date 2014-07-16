"""Generate a python model equivilent to the generated verilog"""

__author__ = "Jon Dawson"
__copyright__ = "Copyright (C) 2013, Jonathan P Dawson"
__version__ = "0.1"

from numpy import uint32
from numpy import int32
from numpy import uint64
from numpy import int64
import struct
import sys

debug = False

class StopSim(Exception):
    pass

def unique(l):

    """In the absence of set in older python implementations, make list values unique"""

    return dict(zip(l, l)).keys()

def calculate_jumps(instructions):

    """change symbolic labels into numeric addresses"""

    #calculate the values of jump locations
    location = 0
    labels = {}
    new_instructions = []
    for instruction in instructions:
       if instruction["op"] == "label":
            labels[instruction["label"]] = location
       else:
            new_instructions.append(instruction)
            location += 1
    instructions = new_instructions

    #substitue real values for labeled jump locations
    for instruction in instructions:
        if "label" in instruction:
            instruction["label"]=labels[instruction["label"]]

    return instructions


def generate_python_model(input_file,
                  name,
                  instructions,
                  allocator,
                  inputs,
                  outputs):

    instructions = calculate_jumps(instructions)

    input_files = unique([i["file_name"] for i in instructions if "file_read" == i["op"]])
    output_files = unique([i["file_name"] for i in instructions if i["op"].endswith("file_write")])

    #map input numbers to port models
    numbered_inputs = {}
    for number, input_name in allocator.input_names.iteritems():
        if input_name in inputs:
            numbered_inputs[number] = inputs[input_name]
    numbered_outputs = {}
    for number, output_name in allocator.output_names.iteritems():
        if output_name in outputs:
            numbered_outputs[number] = outputs[output_name]

    return PythonModel(instructions, allocator.memory_content, input_files, output_files, numbered_inputs, numbered_outputs)


class PythonModel:

    """create a python model equivilent to the generated verilog"""

    def __init__(self, instructions, memory_content, input_files, output_files, inputs, outputs):
        self.instructions = instructions
        self.memory_content = memory_content

        self.input_file_names = input_files
        self.output_file_names = output_files
        self.inputs = inputs
        self.outputs = outputs

    def simulation_reset(self):

        """reset the python model"""

        self.program_counter = 0
        self.register_hi = 0
        self.register_hib = 0
        self.carry = 0
        self.memory = self.memory_content
        self.address = 0
        self.write_state = "wait_ack"
        self.read_state = "wait_stb"

        self.frame = 0
        self.tos = 0
        self.return_frame = 0
        self.new_frame = 0
        self.return_address = 0
        self.pointer = 0
        
        self.input_files = {}
        for file_name in self.input_file_names:
            file_ = open(file_name)
            self.input_files[file_name] = file_

        self.output_files = {}
        for file_name in self.output_file_names:
            file_ = open(file_name, "w")
            self.output_files[file_name] = file_

    def simulation_step(self):

        """execute the python simuilation by one step"""


        instruction = self.instructions[self.program_counter]

        if debug:
            print "executing...", self.program_counter, instruction,
            print "tos:", self.tos,
            print "pointer:", self.pointer,
            print "frame:", self.frame
            for i in range(self.frame, self.tos):
                print i, self.memory.get(i, 0)

        if "literal" in instruction:
            literal = instruction["literal"]

        if "label" in instruction:
            literal = instruction["label"]

        this_instruction = self.program_counter
        self.program_counter += 1

        #put a literal value on the stack
        if instruction["op"] == "push_literal":
           self.memory[self.tos] = int32(literal)
           self.tos += 1

        #reserve memory on the stack
        elif instruction["op"] == "new":
           self.tos += literal

        #free memory on the stack
        elif instruction["op"] == "free":
           self.tos -= literal

        #save the non-volatile pointers
        #remember where the stack frame of the callee function starts
        #push arguments to stack in between this and a call
        elif instruction["op"] == "prologue":
           self.memory[self.tos] = self.new_frame
           self.tos += 1
           self.memory[self.tos] = self.return_frame
           self.tos += 1
           self.memory[self.tos] = self.return_address
           self.tos += 1
           self.new_frame = self.tos

        #restore the non-volatile pointers
        elif instruction["op"] == "epilogue":
           self.tos -= 1
           self.return_address = self.memory.get(self.tos, 0)
           self.tos -= 1
           self.return_frame = self.memory.get(self.tos, 0)
           self.tos -= 1
           self.new_frame = self.memory.get(self.tos, 0)

        #save return address and current frame in non-volatile registers
        #setting the stack frame to point at the first argument
        #call the new function
        elif instruction["op"] == "call":
           self.return_frame = self.frame
           self.return_address = self.program_counter
           self.frame = self.new_frame
           self.program_counter = literal

        #return to the calling function
        #reset the stack pointer to the frame pointer
        #this effectively deletes the callee stack frame
        elif instruction["op"] == "return":
           self.tos = self.frame
           self.frame = self.return_frame
           self.program_counter = self.return_address

        #load the pointer with a literal value, and add the frame pointer
        #this effectively turns a local address within the current frame
        #into a global address.
        elif instruction["op"] == "local":
           self.pointer = literal + self.frame

        #load the pointer with a literal value
        elif instruction["op"] == "global":
           self.pointer = literal

        #convert the local pointer on the top of the stack into a global pointer
        #by adding the frame pointer.
        elif instruction["op"] == "local_to_global":
           self.tos -= 1;
           self.memory[self.tos] = self.memory[self.tos] + self.frame
           self.tos += 1;

        #move the top of the stack to the pointer
        elif instruction["op"] == "pop_global":
           self.tos -= 1;
           self.pointer = self.memory[self.tos] 

        #move n items from the stack to the pointer
        #the literal determines n
        #arrange memory so that the top of the stack goes into a higher numbered address
        elif instruction["op"] == "pop":
           for i in reversed(range(literal)):
               self.tos -= 1;
               self.memory[self.pointer + i] = self.memory.get(self.tos, 0)

        #move n items from the pointer to the stack
        #the literal determines n
        #arrange items so that the higher numbered address ends up on top of the stack
        elif instruction["op"] == "push":
           for i in range(literal):
               self.memory[self.tos] = self.memory.get(self.pointer+i, 0)
               self.tos += 1;

        elif instruction["op"] == "pop_a_lo":
           self.tos -= 1;
           value = self.memory.get(self.tos, 0)
           self.a_lo=value

        elif instruction["op"] == "pop_b_lo":
           self.tos -= 1;
           value = self.memory[self.tos] 
           self.b_lo=value

        elif instruction["op"] == "pop_a_hi":
           self.tos -= 1;
           value = self.memory.get(self.tos, 0)
           self.a_hi=value

        elif instruction["op"] == "pop_b_hi":
           self.tos -= 1;
           value = self.memory[self.tos] 
           self.b_hi=value

        elif instruction["op"] == "push_a_lo":
           self.memory[self.tos] = self.a_lo
           self.tos += 1;

        elif instruction["op"] == "push_a_hi":
           self.memory[self.tos] = self.a_hi
           self.tos += 1;

        elif instruction["op"] == "push_b_lo":
           self.memory[self.tos] = self.b_lo
           self.tos += 1;

        elif instruction["op"] == "push_b_hi":
           self.memory[self.tos] = self.b_hi
           self.tos += 1;

        elif instruction["op"] == "not":
           self.registers[dest] = int32(~self.registers[src])

        elif instruction["op"] == "int_to_long":
           self.tos -= 1
           if self.memory.get(self.tos, 0) & 0x80000000:
               self.tos += 1
               self.memory[self.tos] = 0xffffffff
               self.tos += 1
           else:
               self.tos += 1
               self.memory[self.tos] = 0x00000000
               self.tos += 1

        elif instruction["op"] == "int_to_float":
           f = float(self.a_lo)
           self.a_lo = int32(float_to_bits(f))

        elif instruction["op"] == "float_to_int":
           i = bits_to_float(self.a_lo)
           self.a_lo = int32(i)

        elif instruction["op"] == "long_to_double":
           double = float(join_words(self.a_hi, self.a_lo))
           self.a_hi, self.a_lo = split_word(double_to_bits(double))

        elif instruction["op"] == "double_to_long":
           bits = int(bits_to_double(join_words(self.a_hi, self.a_lo)))
           self.a_hi, self.a_lo = split_word(bits)

        elif instruction["op"] == "float_to_double":
           f = bits_to_float(self.a_lo)
           bits = double_to_bits(f)
           self.a_hi, self.a_lo = split_word(bits)

        elif instruction["op"] == "double_to_float":
           f = bits_to_double(join_words(self.a_hi, self.a_lo))
           bits = float_to_bits(f)
           self.a_lo = bits

        elif instruction["op"] == "add":
           self.tos -= 1
           b = self.memory[self.tos]
           self.tos -= 1
           a = self.memory[self.tos]
           lw = int(uint32(a)) + int(uint32(b))
           self.carry, self.memory[self.tos] = split_word(lw)
           self.carry &= 1
           self.tos += 1

        elif instruction["op"] == "add_with_carry":
           self.tos -= 1
           b = self.memory[self.tos]
           self.tos -= 1
           a = self.memory[self.tos]
           lw = int(uint32(a)) + int(uint32(b)) + self.carry
           self.carry, self.memory[self.tos] = split_word(lw)
           self.carry &= 1
           self.tos += 1

        elif instruction["op"] == "subtract":
           self.tos -= 1
           b = self.memory[self.tos]
           self.tos -= 1
           a = self.memory[self.tos]
           lw = int(uint32(a)) + ~int(uint32(b)) + 1
           self.carry, self.memory[self.tos] = split_word(lw)
           self.carry &= 1
           self.carry ^= 1
           self.tos += 1

        elif instruction["op"] == "subtract_with_carry":
           self.tos -= 1
           b = self.memory[self.tos]
           self.tos -= 1
           a = self.memory[self.tos]
           lw = int(uint32(a)) + ~int(uint32(b)) + self.carry
           self.carry, self.memory[self.tos] = split_word(lw)
           self.carry &= 1
           self.carry ^= 1
           self.tos += 1

        elif instruction["op"] == "multiply":
           #tos   => a
           #tos-1 => b
           self.tos -= 1
           b = self.memory[self.tos]
           self.tos -= 1
           a = self.memory[self.tos]
           lw = int(uint32(a)) * int(uint32(b))
           self.register_hi, self.memory[self.tos] = split_word(lw)
           self.tos += 1

        elif instruction["op"] == "or":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           self.memory[self.tos] = int32( uint32(a) | uint32(b))
           self.tos += 1

        elif instruction["op"] == "and":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           self.memory[self.tos] = int32( uint32(a) & uint32(b))
           self.tos += 1

        elif instruction["op"] == "xor":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           self.memory[self.tos] = int32( uint32(a) ^ uint32(b))
           self.tos += 1

        elif instruction["op"] == "shift_left":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           b &= 0x3f
           self.carry = uint32(a >> (32 - b))
           self.memory[self.tos] = uint32(a << b)
           self.tos += 1

        elif instruction["op"] == "shift_left_with_carry":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           b &= 0x3f
           carry_in = self.carry
           self.carry = uint32(a >> (32 - b))
           self.memory[self.tos] = uint32(a << b) | carry_in
           self.tos += 1

        elif instruction["op"] == "shift_right":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           b &= 0x3f
           self.carry = uint32(a << (32 - b))
           self.memory[self.tos] = int32(a >> b)
           self.tos += 1

        elif instruction["op"] == "unsigned_shift_right":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           b &= 0x3f
           self.carry = uint32(a << (32 - b))
           self.memory[self.tos] = uint32(a) >> b
           self.tos += 1

        elif instruction["op"] == "shift_right_with_carry":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           b &= 0x3f
           carry_in = self.carry
           self.carry = unit32(a << (32 - b))
           self.memory[self.tos] = uint32(a) >> b | carry_in
           self.tos += 1

        elif instruction["op"] == "greater":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           self.memory[self.tos] = int32(int32(a) > int32(b))
           self.tos += 1

        elif instruction["op"] == "greater_equal":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           self.memory[self.tos] = int32(int32(a) >= int32(b))
           self.tos += 1

        elif instruction["op"] == "unsigned_greater":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           self.memory[self.tos] = int32(uint32(a) > uint32(b))
           self.tos += 1

        elif instruction["op"] == "unsigned_greater_equal":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           self.memory[self.tos] = int32(uint32(a) >= uint32(b))
           self.tos += 1

        elif instruction["op"] == "equal":
           self.tos -= 1
           b = self.memory.get(self.tos, 0)
           self.tos -= 1
           a = self.memory.get(self.tos, 0)
           self.memory[self.tos] = int32(int32(a) == int32(b))
           self.tos += 1

        elif instruction["op"] == "not_equal":
           self.registers[dest] = int32(int32(self.registers[src]) != int32(self.registers[srcb]))

        elif instruction["op"] == "float_add":
           float_ = bits_to_float(self.a_lo)
           floatb = bits_to_float(self.b_lo)
           result = float_ + floatb
           self.a_lo = float_to_bits(result)

        elif instruction["op"] == "float_subtract":
           float_ = bits_to_float(self.a_lo)
           floatb = bits_to_float(self.b_lo)
           result = float_ - floatb
           self.a_lo = float_to_bits(result)

        elif instruction["op"] == "float_multiply":
           float_ = bits_to_float(self.a_lo)
           floatb = bits_to_float(self.b_lo)
           result = float_ * floatb
           self.a_lo = float_to_bits(result)

        elif instruction["op"] == "float_divide":
           float_ = bits_to_float(self.a_lo)
           floatb = bits_to_float(self.b_lo)
           result = float_ / floatb
           self.a_lo = float_to_bits(result)

        elif instruction["op"] == "long_float_add":
           double = bits_to_double(join_words(self.a_hi, self.a_lo))
           doubleb = bits_to_double(join_words(self.b_hi, self.a_lo))
           result = double + doubleb
           self.a_hi, self.a_lo = split_word(double_to_bits(result))

        elif instruction["op"] == "long_float_subtract":
           double = bits_to_double(join_words(self.a_hi, self.a_lo))
           doubleb = bits_to_double(join_words(self.b_hi, self.b_lo))
           result = double - doubleb
           self.a_hi, self.a_lo = split_word(double_to_bits(result))

        elif instruction["op"] == "long_float_multiply":
           double = bits_to_double(join_words(self.a_hi, self.a_lo))
           doubleb = bits_to_double(join_words(self.b_hi, self.b_lo))
           result = double * doubleb
           self.a_hi, self.a_lo = split_word(double_to_bits(result))

        elif instruction["op"] == "long_float_divide":
           double = bits_to_double(join_words(self.a_hi, self.a_lo))
           doubleb = bits_to_double(join_words(self.b_hi, self.b_lo))
           result = double / doubleb
           self.a_hi, self.a_lo = split_word(double_to_bits(result))

        elif instruction["op"] == "jmp_if_false":
            self.tos -= 1
            if self.memory[self.tos] == 0:
                self.program_counter = literal

        elif instruction["op"] == "jmp_if_true":
            self.tos -= 1
            if self.memory.get(self.tos, 0) != 0:
                self.program_counter = literal

        elif instruction["op"] == "goto":
            self.program_counter = literal

        elif instruction["op"] == "file_read":
            value = self.input_files[instruction["filename"]].getline()
            self.memory[self.tos] = int32(value)
            self.tos += 1

        elif instruction["op"] == "float_file_write":
            self.tos -= 1
            self.output_files[instruction["file_name"]].write("%f\n"%bits_to_float(self.memory.get(self.tos, 0)))

        elif instruction["op"] == "long_float_file_write":
            long_word = join_words(self.a_hi, self.a_lo)
            self.output_files[instruction["file_name"]].write("%f\n"%bits_to_double(long_word))

        elif instruction["op"] == "unsigned_file_write":
            self.tos -= 1
            self.output_files[instruction["file_name"]].write("%i\n"%uint32(self.memory.get(self.tos, 0)))

        elif instruction["op"] == "file_write":
            self.tos -= 1
            self.output_files[instruction["file_name"]].write("%i\n"%int32(self.memory.get(self.tos, 0)))

        elif instruction["op"] == "long_file_write":
            long_word = join_words(self.a_hi, self.a_lo)
            self.output_files[instruction["file_name"]].write("%f\n"%long_word)

        elif instruction["op"] == "read":


            if self.registers[src] not in self.inputs:

                self.registers[dest] = 0

            else:

                input_ = self.inputs[self.registers[src]]
                self.program_counter = this_instruction

                if self.read_state == "wait_stb":
                    if input_.stb:
                        input_.ack = True
                        self.read_state = "wait_nstb"
                        self.registers[dest] = input_.data
                elif self.read_state == "wait_nstb":
                    if not input_.stb:
                        input_.ack = False
                        self.read_state = "wait_stb"
                        self.program_counter += 1

        elif instruction["op"] == "ready":
            if self.registers[src] not in self.inputs:
                self.registers[dest] = 0
            else:
                input_ = self.inputs[self.registers[src]]
                self.registers[dest] = int32(int(input_.stb))

        elif instruction["op"] == "write":

            if self.registers[src] not in self.outputs:

                pass

            else:

                output = self.outputs[self.registers[src]]
                output.data = self.registers[srcb]
                self.program_counter = this_instruction

                if self.write_state == "wait_ack":
                    output.stb = True
                    if output.ack:
                        output.stb = False
                        self.write_state = "wait_nack"
                elif self.write_state == "wait_nack":
                    if not output.ack:
                        self.write_state = "wait_ack"
                        self.program_counter += 1

        elif instruction["op"] == "memory_read":
            self.address = self.registers[src]
            self.registers[dest] = int32(self.memory.get(self.address, 0))

        elif instruction["op"] == "memory_write":
            self.memory[self.registers[src]] = int32(self.registers[srcb])

        elif instruction["op"] == "assert":
            if self.a_lo == 0:
                print "(assertion failed at line: %s in file: %s)"%(
                instruction["line"],
                instruction["file"])
                exit(1)

        elif instruction["op"] == "report":
            print "%d (report (int) at line: %s in file: %s)"%(
                self.a_lo,
                instruction["line"],
                instruction["file"],
            )

        elif instruction["op"] == "long_report":
            print "%d (report (long) at line: %s in file: %s)"%(
                join_words(self.a_hi, self.a_lo),
                instruction["line"],
                instruction["file"],
            )

        elif instruction["op"] == "float_report":
            print "%f (report (float) at line: %s in file: %s)"%(
                bits_to_float(self.a_lo),
                instruction["line"],
                instruction["file"],
            )

        elif instruction["op"] == "long_float_report":
            print "%s (report (double) at line: %s in file: %s)"%(
                bits_to_double(join_words(self.a_hi, self.a_lo)),
                instruction["line"],
                instruction["file"],
            )

        elif instruction["op"] == "unsigned_report":
            print "%d (report (unsigned) at line: %s in file: %s)"%(
                uint32(self.a_lo),
                instruction["line"],
                instruction["file"],
            )

        elif instruction["op"] == "long_unsigned_report":
            print "%d (report (unsigned long) at line: %s in file: %s)"%(
                uint64(join_words(self.a_hi, self.a_lo)),
                instruction["line"],
                instruction["file"],
            )

        elif instruction["op"] == "stop":
            self.program_counter = this_instruction
            for file_ in self.input_files.values():
                file_.close()
            for file_ in self.output_files.values():
                file_.close()
            raise StopSim
        else:
            print "Unknown machine instruction", instruction["op"]
            sys.exit(0)

def float_to_bits(f):
    
    "convert a floating point number into an integer containing the ieee 754 representation."

    value = 0
    for byte in struct.pack(">f", f):
         value <<= 8
         value |= ord(byte)
    return int32(value)

def double_to_bits(f):

    "convert a double precision floating point number into a 64 bit integer containing the ieee 754 representation."

    value = 0
    for byte in struct.pack(">d", f):
         value <<= 8
         value |= ord(byte) 
    return uint64(value)

def bits_to_float(bits):

    "convert integer containing the ieee 754 representation into a float"

    byte_string = (
        chr((bits & 0xff000000) >> 24) +
        chr((bits & 0xff0000) >> 16) +
        chr((bits & 0xff00) >> 8) +
        chr((bits & 0xff))
    )
    return struct.unpack(">f", byte_string)[0]

def bits_to_double(bits):

    "convert integer containing the ieee 754 representation into a float"

    bits = int(bits)
    byte_string = (
        chr((bits & 0xff00000000000000) >> 56) +
        chr((bits & 0xff000000000000) >> 48) +
        chr((bits & 0xff0000000000) >> 40) +
        chr((bits & 0xff00000000) >> 32) +
        chr((bits & 0xff000000) >> 24) +
        chr((bits & 0xff0000) >> 16) +
        chr((bits & 0xff00) >> 8) +
        chr((bits & 0xff))
    )
    return struct.unpack(">d", byte_string)[0]

def join_words(hi, lo):

    """join two 32 bit words into a 64 bit word"""

    return int64((int(hi) << 32) | (int(lo) & 0xffffffff))

def split_word(lw):

    """split a 64 bit words into two 32 bit words"""

    return int32(int(lw) >> 32), int32(int(lw) & 0xffffffff)
