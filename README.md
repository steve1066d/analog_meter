# analog_meter: Reads an AC-250 gas meter by monitoring the 2cfm dial
    by Steve Devore steve1066d@yahoo.com

    I'm using a Raspberry PI, with the HQ camera (HQ because I needed a lens that could be mounted close to the meter).
    It should work fine with the standard camera as well. The basic approach is to use opencv to find the correct dial,
    and save the dial positions. I got more consistent results only looking for the dials one time, as opencv doesn't
    exactly line up the circles between shots.

    It then reads the top ccf dials for the starting position. Next, it looks at the 2cf dial and keeps track of the
    position and revolutions to report the cumulative cubic feet used.

    The take_picture method should return a cropped grayscale photo of the meter display. The example photo contains an
    example of the source image of my setup.

    For debugging, if it is run on a system without the camera, it will instead use a series of photos instead
    The series can be created by enabling saveImages.
    
